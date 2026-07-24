package com.reasonix.security.guardian;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.reasonix.security.breaker.CircuitBreaker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.model.ChatModel;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.chat.prompt.SystemPromptTemplate;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Guardian — Spring AI 驱动的 LLM 安全审查 + 熔断器。
 *
 * 核心流程：
 * 1. 接收父会话增量转录 + 待审查工具调用
 * 2. Spring AI 调用 DeepSeek (OpenAI-compatible)
 * 3. JSON 解析 → GuardianVerdict
 * 4. 硬策略覆盖（critical 永远 deny、high+低授权 deny）
 * 5. Redis 熔断器更新
 *
 * 映射 Go 的 internal/guardian/guardian.go
 */
@Service
public class GuardianService {

    private static final Logger log = LoggerFactory.getLogger(GuardianService.class);

    private static final String SYSTEM_PROMPT = """
            You are a safety gate. You are NOT a coding agent.
            Evaluate each tool call and output a JSON verdict.

            Risk levels:
            - low: routine, narrow scope
            - medium: bounded blast radius
            - high: dangerous or costly to reverse
            - critical: credential exfiltration or persistent weakening

            User authorization levels:
            - high: user explicitly requested this action
            - medium: user discussed the substance but not the exact form
            - low: weak or ambiguous evidence
            - unknown: no evidence of user intent

            Rules:
            - low → allow
            - medium → allow
            - high → allow only if user_authorization >= medium, else deny
            - critical → deny always
            - Destructive actions (rm -rf outside workspace, force-push to main) → high or critical
            - Exposing secrets/credentials to untrusted destinations → critical
            - User re-approves a previously denied action → user_authorization=high, allow

            Output EXACTLY this JSON (no markdown, no extra text):
            {"risk_level":"low|medium|high|critical","user_authorization":"unknown|low|medium|high","outcome":"allow|deny","rationale":"one sentence"}
            """;

    @Autowired
    private ChatModel chatModel;

    @Autowired
    private CircuitBreaker circuitBreaker;

    private final ObjectMapper mapper = new ObjectMapper();

    // 每个 session 的转录光标（ConcurrentHashMap，sessionId → TranscriptCursor）
    private final ConcurrentHashMap<String, TranscriptCursor> cursors = new ConcurrentHashMap<>();

    /**
     * 审查一个工具调用。
     * @param toolName 工具名
     * @param argsJson 参数字符串
     * @param transcriptJson 父会话转录的 JSON 数组
     * @param sessionId 会话 ID（用于熔断器 + 光标跟踪）
     * @return GuardianVerdict (protobuf)
     */
    public com.reasonix.security.grpc.GuardianVerdict review(
            String toolName, String argsJson, String transcriptJson, String sessionId) {

        // 1. 增量转录
        var cursor = cursors.computeIfAbsent(sessionId, k -> new TranscriptCursor());
        var delta = cursor.delta(transcriptJson);

        // 2. 规则覆盖 — 独立于 LLM 的硬规则，防止提示注入绕过
        var ruleOverride = ruleBasedCheck(toolName, argsJson);
        if (ruleOverride != null) {
            log.info("Guardian rule override: tool={} outcome={}", toolName, ruleOverride);
            return buildVerdict("critical", ruleOverride, "Rule-based override");
        }

        // 3. 构建 Spring AI Prompt（截断输入防止提示注入）
        var safeDelta = truncate(delta, 5000);
        var safeArgs = truncate(argsJson, 1000);
        var prompt = new Prompt(
                new SystemPromptTemplate(SYSTEM_PROMPT).createMessage(),
                new UserMessage("""
                        Transcript:
                        %s

                        Tool call to review:
                          Name: %s
                          Args: %s
                        """.formatted(safeDelta, toolName, safeArgs))
        );

        // 3. 调用 LLM（Spring AI → DeepSeek via OpenAI-compatible API）
        String content;
        try {
            var response = chatModel.call(prompt);
            content = response.getResult().getOutput().getText();
        } catch (Exception e) {
            log.error("Guardian LLM call failed: {}", e.getClass().getSimpleName());
            return buildVerdict("unknown", "deny", "Guardian model unavailable");
        }

        // 4. 解析 JSON 判决
        var verdict = parseVerdict(content);

        // 5. 硬策略覆盖（Go 的 enforcePolicyRules）
        verdict = enforceHardPolicy(verdict);

        // 6. 熔断器更新（Redis 持久化）
        if ("deny".equals(verdict.outcome)) {
            boolean tripped = circuitBreaker.recordDenial(sessionId);
            if (tripped) {
                log.warn("Guardian breaker tripped for session {}", sessionId);
                return buildVerdict(verdict.riskLevel, "deny",
                        "Guardian circuit breaker tripped. " + circuitBreaker.getReason(sessionId));
            }
        } else {
            circuitBreaker.recordAllow(sessionId);
        }

        log.info("Guardian: tool={} risk={} auth={} outcome={}",
                toolName, verdict.riskLevel, verdict.userAuthorization,
                verdict.outcome);

        return buildVerdict(verdict.riskLevel, verdict.outcome, verdict.rationale);
    }

    /**
     * 硬策略覆盖 — 映射 Go 的 enforcePolicyRules()。
     * LLM 的输出必须经过这些规则，不能被 bypass。
     */
    GuardianVerdict enforceHardPolicy(GuardianVerdict v) {
        var risk = v.riskLevel != null ? v.riskLevel : "unknown";
        var auth = v.userAuthorization != null ? v.userAuthorization : "unknown";
        var outcome = v.outcome;

        if ("critical".equals(risk)) {
            outcome = "deny";  // critical → 永远 deny
        } else if ("high".equals(risk)
                && ("unknown".equals(auth) || "low".equals(auth))) {
            outcome = "deny";  // high + 低授权 → deny
        }

        return new GuardianVerdict(risk, auth, outcome, v.rationale);
    }

    /** 解析 LLM 返回的 JSON 字符串 — 默认 deny，防止注入绕过 */
    GuardianVerdict parseVerdict(String json) {
        try {
            @SuppressWarnings("unchecked")
            var map = mapper.readValue(json, Map.class);
            return new GuardianVerdict(
                    safeStr(map.get("risk_level"), "unknown"),
                    safeStr(map.get("user_authorization"), "unknown"),
                    safeStr(map.get("outcome"), "deny"),  // 默认 deny
                    safeStr(map.get("rationale"), "")
            );
        } catch (Exception e) {
            log.warn("Failed to parse guardian verdict JSON: {}",
                    e.getClass().getSimpleName());
            return new GuardianVerdict("unknown", "unknown", "deny",
                    "Guardian returned an invalid verdict");
        }
    }

    private com.reasonix.security.grpc.GuardianVerdict buildVerdict(
            String risk, String outcome, String rationale) {
        return com.reasonix.security.grpc.GuardianVerdict.newBuilder()
                .setRiskLevel(risk != null ? risk : "unknown")
                .setOutcome(outcome != null ? outcome : "deny")
                .setRationale(rationale != null ? rationale : "")
                .build();
    }

    private static String safeStr(Object val, String fallback) {
        return val instanceof String s && !s.isBlank() ? s : fallback;
    }

    /** 基于规则的检查 — 在 LLM 调用之前拦截危险操作。防止提示注入绕过。 */
    public String ruleBasedCheck(String toolName, String argsJson) {
        if (argsJson == null) return null;
        var lower = argsJson.toLowerCase();

        // 危险文件操作
        if (lower.contains("rm -rf /") || lower.contains("rm -rf /*")) return "deny";
        // 危险 git 操作
        if (lower.contains("git push --force") || lower.contains("git push -f")) return "deny";
        // 凭据泄露
        if (lower.contains("/etc/shadow") || lower.contains("/etc/passwd")) return "deny";
        // 系统修改
        if (lower.contains("chmod 777") || lower.contains("chown")) return "deny";
        // 危险命令
        if (lower.contains("> /dev/sda") || lower.contains("mkfs")) return "deny";

        return null; // 未匹配任何规则，走 LLM 审查
    }

    private static String truncate(String s, int max) {
        return s != null && s.length() > max ? s.substring(0, max) + "..." : s;
    }

    /** 内部记录：guardian 判决的纯 Java 表示 */
    record GuardianVerdict(String riskLevel, String userAuthorization, String outcome, String rationale) {}
}
