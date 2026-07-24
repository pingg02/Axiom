package com.reasonix.security.secrets;

import org.springframework.stereotype.Service;

import java.util.regex.Pattern;

/**
 * Secrets redaction — 正则匹配 + mask 脱敏。
 * 映射 Go 的 internal/secrets/redact.go。
 */
@Service
public class SecretsRedactor {

    private static final Pattern KEY_VALUE = Pattern.compile(
            "(?i)\\b([A-Z0-9_.-]*(?:API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD)[A-Z0-9_.-]*)\\b(['\"]?\\s*[:=]\\s*['\"]?)([^'\"\\s,;]+)"
    );
    private static final Pattern BEARER = Pattern.compile(
            "(?i)\\bBearer\\s+([A-Za-z0-9._~+/=-]{16,})"
    );
    private static final Pattern OPENAI_KEY = Pattern.compile(
            "\\b((?:sk|rk)-(?:proj-)?[A-Za-z0-9_-]{12,})\\b"
    );
    private static final Pattern GITHUB_TOKEN = Pattern.compile(
            "\\b(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\\b"
    );
    private static final Pattern JWT = Pattern.compile(
            "\\b(eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+)\\b"
    );

    private static final String REDACTED = "[redacted]";

    private boolean enabled = true;

    public String redact(String text, boolean redactToolOutput) {
        if (!redactToolOutput || !enabled) {
            return text;
        }
        return applyPatterns(text);
    }

    public String redactAlways(String text) {
        return applyPatterns(text);
    }

    private String applyPatterns(String text) {
        text = KEY_VALUE.matcher(text).replaceAll(mr -> {
            String value = mr.group(3);
            return mr.group(1) + mr.group(2) + mask(value);
        });
        text = BEARER.matcher(text).replaceAll("Bearer " + REDACTED);
        text = OPENAI_KEY.matcher(text).replaceAll(mr -> mask(mr.group(1)));
        text = GITHUB_TOKEN.matcher(text).replaceAll(mr -> mask(mr.group(1)));
        text = JWT.matcher(text).replaceAll(mr -> mask(mr.group(1)));
        return text;
    }

    public static String mask(String value) {
        if (value == null || value.length() <= 12) return REDACTED;
        int head = value.startsWith("sk-") || value.startsWith("rk-") ? 6 : 4;
        int tail = 4;
        if (value.length() <= head + tail) return REDACTED;
        return value.substring(0, head)
                + "*".repeat(value.length() - head - tail)
                + value.substring(value.length() - tail);
    }
}
