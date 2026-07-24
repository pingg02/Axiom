package com.reasonix.security.breaker;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Redis-backed guardian circuit breaker.
 *
 * The in-memory fallback is used when the class is constructed directly in unit
 * tests, where Spring has not injected Redis.
 */
@Service
public class CircuitBreaker {

    private static final Logger log = LoggerFactory.getLogger(CircuitBreaker.class);

    static final int MAX_CONSECUTIVE = 3;
    static final int MAX_RECENT = 10;
    static final int WINDOW = 50;
    private static final Duration TTL = Duration.ofMinutes(30);

    @Autowired(required = false)
    private StringRedisTemplate redis;

    private final Map<String, LocalState> localStates = new ConcurrentHashMap<>();

    private static final String RECORD_DENIAL_SCRIPT = String.format("""
            local con_key = KEYS[1]
            local win_key = KEYS[2]
            local trip_key = KEYS[3]
            local ttl = ARGV[1]

            local consecutive = redis.call('INCR', con_key)
            redis.call('EXPIRE', con_key, ttl)

            redis.call('RPUSH', win_key, '1')
            redis.call('LTRIM', win_key, -%d, -1)
            redis.call('EXPIRE', win_key, ttl)

            local entries = redis.call('LRANGE', win_key, 0, -1)
            local denials = 0
            for i = 1, #entries do
                if entries[i] == '1' then denials = denials + 1 end
            end

            if (consecutive >= %d or tonumber(denials) >= %d) then
                local tripped = redis.call('EXISTS', trip_key)
                if tripped == 0 then
                    redis.call('SET', trip_key, 'true', 'EX', ttl)
                    return 1
                end
            end
            return 0
            """, WINDOW, MAX_CONSECUTIVE, MAX_RECENT);

    private static final String RECORD_ALLOW_SCRIPT = String.format("""
            local con_key = KEYS[1]
            local win_key = KEYS[2]

            redis.call('DEL', con_key)
            redis.call('RPUSH', win_key, '0')
            redis.call('LTRIM', win_key, -%d, -1)
            redis.call('EXPIRE', win_key, %d)
            return 0
            """, WINDOW, TTL.toSeconds());

    private final DefaultRedisScript<Long> denialScript =
            new DefaultRedisScript<>(RECORD_DENIAL_SCRIPT, Long.class);
    private final DefaultRedisScript<Long> allowScript =
            new DefaultRedisScript<>(RECORD_ALLOW_SCRIPT, Long.class);

    public boolean recordDenial(String sessionId) {
        if (redis == null) {
            return recordLocalDenial(sessionId);
        }

        var keys = keys(sessionId);
        var result = redis.execute(denialScript, keys, String.valueOf(TTL.toSeconds()));
        boolean tripped = result != null && result == 1;
        if (tripped) {
            log.warn("Circuit breaker tripped for session: {}", sessionId);
        }
        return tripped;
    }

    public void recordAllow(String sessionId) {
        if (redis == null) {
            localStates.computeIfAbsent(sessionId, ignored -> new LocalState()).recordAllow();
            return;
        }

        var keys = List.of(
                "guardian:breaker:" + sessionId + ":consecutive",
                "guardian:breaker:" + sessionId + ":recent"
        );
        redis.execute(allowScript, keys);
    }

    public void resetTurn(String sessionId) {
        if (redis == null) {
            localStates.remove(sessionId);
            return;
        }

        var prefix = "guardian:breaker:" + sessionId + ":*";
        var keys = redis.keys(prefix);
        if (keys != null && !keys.isEmpty()) {
            redis.delete(keys);
        }
    }

    public String getReason(String sessionId) {
        if (redis == null) {
            var state = localStates.getOrDefault(sessionId, new LocalState());
            return formatReason(state.tripped, state.consecutive, state.recentDenials());
        }

        var conKey = "guardian:breaker:" + sessionId + ":consecutive";
        var winKey = "guardian:breaker:" + sessionId + ":recent";
        var tripKey = "guardian:breaker:" + sessionId + ":tripped";

        var consecutive = redis.opsForValue().get(conKey);
        var recent = redis.opsForList().size(winKey);
        var tripped = redis.hasKey(tripKey);

        return String.format(
                "Guardian circuit breaker %s (%s consecutive / %d in recent %d). Report to user.",
                Boolean.TRUE.equals(tripped) ? "TRIPPED" : "closed",
                consecutive != null ? consecutive : "0",
                recent != null ? recent : 0,
                WINDOW);
    }

    private boolean recordLocalDenial(String sessionId) {
        var state = localStates.computeIfAbsent(sessionId, ignored -> new LocalState());
        boolean firstTrip = state.recordDenial();
        if (firstTrip) {
            log.warn("Circuit breaker tripped for session: {}", sessionId);
        }
        return firstTrip;
    }

    private static String formatReason(boolean tripped, int consecutive, int recent) {
        return String.format(
                "Guardian circuit breaker %s (%d consecutive / %d in recent %d). Report to user.",
                tripped ? "TRIPPED" : "closed",
                consecutive,
                recent,
                WINDOW);
    }

    private List<String> keys(String sessionId) {
        return List.of(
                "guardian:breaker:" + sessionId + ":consecutive",
                "guardian:breaker:" + sessionId + ":recent",
                "guardian:breaker:" + sessionId + ":tripped"
        );
    }

    private static final class LocalState {
        private int consecutive = 0;
        private boolean tripped = false;
        private final Deque<Boolean> recent = new ArrayDeque<>();

        private boolean recordDenial() {
            consecutive += 1;
            appendRecent(true);
            boolean shouldTrip = consecutive >= MAX_CONSECUTIVE || recentDenials() >= MAX_RECENT;
            if (shouldTrip && !tripped) {
                tripped = true;
                return true;
            }
            return false;
        }

        private void recordAllow() {
            consecutive = 0;
            appendRecent(false);
        }

        private int recentDenials() {
            int count = 0;
            for (boolean denial : recent) {
                if (denial) {
                    count += 1;
                }
            }
            return count;
        }

        private void appendRecent(boolean denial) {
            recent.addLast(denial);
            while (recent.size() > WINDOW) {
                recent.removeFirst();
            }
        }
    }
}
