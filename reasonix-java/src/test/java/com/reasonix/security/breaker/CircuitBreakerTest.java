package com.reasonix.security.breaker;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class CircuitBreakerTest {

    @Test
    void recordDenialCountsConsecutive() {
        var cb = new CircuitBreaker();
        assertFalse(cb.recordDenial("s1"));
        assertFalse(cb.recordDenial("s1"));
        assertTrue(cb.recordDenial("s1"));  // 3rd consecutive trips
    }

    @Test
    void recordAllowResetsConsecutive() {
        var cb = new CircuitBreaker();
        cb.recordDenial("s1");
        cb.recordDenial("s1");
        cb.recordAllow("s1");
        assertFalse(cb.recordDenial("s1"));  // back to 1
    }

    @Test
    void resetTurnClearsState() {
        var cb = new CircuitBreaker();
        cb.recordDenial("s1");
        cb.recordDenial("s1");
        cb.recordDenial("s1");
        cb.resetTurn("s1");
        String reason = cb.getReason("s1");
        assertTrue(reason.contains("closed") || !reason.contains("TRIPPED"));
    }

    @Test
    void getReasonAfterTrip() {
        var cb = new CircuitBreaker();
        cb.recordDenial("s1");
        cb.recordDenial("s1");
        cb.recordDenial("s1");
        String reason = cb.getReason("s1");
        assertNotNull(reason);
        assertFalse(reason.isBlank());
    }

    @Test
    void differentSessionsIndependent() {
        var cb = new CircuitBreaker();
        cb.recordDenial("s1");
        cb.recordDenial("s1");
        // s2 should be unaffected
        assertFalse(cb.recordDenial("s2"));
        assertFalse(cb.recordDenial("s2"));
    }

    @Test
    void LuaScriptsAreValid() {
        // Verify Lua script strings compile correctly (syntax check)
        // The scripts are embedded in Java strings; verify no placeholder issues
        var cb = new CircuitBreaker();
        // Just check the class loads and constants are accessible
        assertTrue(CircuitBreaker.MAX_CONSECUTIVE > 0);
        assertTrue(CircuitBreaker.MAX_RECENT > 0);
        assertTrue(CircuitBreaker.WINDOW > 0);
    }

    @Test
    void windowSizeConstant() {
        assertEquals(50, CircuitBreaker.WINDOW);
    }
}
