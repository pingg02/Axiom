package com.reasonix.security.permission;

import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * Permission Gate — Allow/Ask/Deny 三级决策。
 *
 * 规则匹配 + Bash 复合命令拆解（&& / || / ; 每段独立评估）。
 *
 * 映射 Go 的 internal/permission/permission.go
 * 映射 Python 的 reasonix/permission/permission.py
 */
@Service
public class PermissionGate {

    public enum Decision { ALLOW, ASK, DENY }

    private final Policy policy = Policy.fromConfig(
            List.of("Bash(rm -rf *)"),
            List.of(),
            List.of(),
            Decision.ASK);

    public Decision decide(String toolName, boolean readOnly, String argsJson) {
        if (toolName == null) return Decision.ASK;
        var subject = subjectFromArgs(toolName, argsJson);

        // Bash 复合命令特殊处理
        if ("bash".equals(toolName)) {
            return decideBash(readOnly, subject);
        }
        return decideSubject(toolName, readOnly, subject);
    }

    /**
     * Bash 决策 — 拆解复合命令，逐段评估。
     * 映射 Python 的 _decide_bash()。
     */
    private Decision decideBash(boolean readOnly, String command) {
        var segments = decomposeBash(command);
        if (segments == null || segments.isEmpty()) {
            return decideSubject("bash", readOnly, command);
        }

        var outcome = Decision.ALLOW;
        for (var seg : segments) {
            var segReadOnly = readOnly || isReadOnlyBash(seg);
            var d = decideSubject("bash", segReadOnly, seg.trim());
            if (d == Decision.DENY) return Decision.DENY;
            if (d == Decision.ASK) outcome = Decision.ASK;
        }
        return outcome;
    }

    /**
     * 核心优先级链：Deny > SessionAllow > Ask > Allow > readOnly回退 > writer回退(mode)
     */
    private Decision decideSubject(String toolName, boolean readOnly, String subject) {
        for (var r : policy.deny)       if (r.matches(toolName, subject)) return Decision.DENY;
        for (var r : policy.sessionAllow) if (r.matches(toolName, subject)) return Decision.ALLOW;
        for (var r : policy.ask)        if (r.matches(toolName, subject)) return Decision.ASK;
        for (var r : policy.allow)      if (r.matches(toolName, subject)) return Decision.ALLOW;
        if (readOnly) return Decision.ALLOW;
        return policy.mode;
    }

    // ── Bash 复合命令拆解 ─────────────────────────────────────────────────

    /**
     * 将复合 bash 命令拆解为独立段。
     * "echo a && rm -rf / || echo b" → ["echo a", "rm -rf /", "echo b"]
     */
    static List<String> decomposeBash(String command) {
        if (command == null || command.isBlank()) return List.of();

        var parts = command.split("\\s*(?:&&|\\|\\||;)\\s*");
        var result = new ArrayList<String>();
        for (var p : parts) {
            var trimmed = p.trim();
            if (!trimmed.isEmpty()) {
                result.add(trimmed);
            }
        }
        return result.size() > 1 ? result : List.of();
    }

    private static final Set<String> READONLY_COMMANDS = Set.of(
            "echo", "ls", "cat", "head", "tail", "grep", "find",
            "pwd", "which", "whoami", "date", "env", "printenv"
    );

    private static final List<String> READONLY_MULTI_WORD = List.of(
            "git status", "git diff", "git log", "git show", "git branch"
    );

    static boolean isReadOnlyBash(String command) {
        if (command == null || command.isBlank()) return false;
        var trimmed = command.trim().toLowerCase();
        // 检查多词命令
        for (var mw : READONLY_MULTI_WORD) {
            if (trimmed.startsWith(mw)) return true;
        }
        // 检查单字命令
        var first = trimmed.split("\\s+")[0];
        return READONLY_COMMANDS.contains(first);
    }

    // ── 工具调用参数提取 ──────────────────────────────────────────────────

    static String subjectFromArgs(String toolName, String argsJson) {
        if (argsJson == null || argsJson.isBlank()) return "";
        try {
            if ("bash".equals(toolName)) {
                return extractField(argsJson, "command");
            }
            var path = extractField(argsJson, "path");
            if (path != null) return path;
            var oldStr = extractField(argsJson, "old_string");
            if (oldStr != null) return oldStr;
            return argsJson;
        } catch (Exception e) {
            return argsJson;
        }
    }

    private static String extractField(String json, String field) {
        var quote = "\"" + field + "\"";
        var idx = json.indexOf(quote);
        if (idx < 0) return null;
        var colon = json.indexOf(':', idx + quote.length());
        if (colon < 0) return null;
        var start = json.indexOf('"', colon + 1);
        if (start < 0) return null;
        var end = start + 1;
        while (end < json.length() && json.charAt(end) != '"') {
            if (json.charAt(end) == '\\') end++;
            end++;
        }
        return json.substring(start + 1, end);
    }

    // ── 规则引擎 ──────────────────────────────────────────────────────────

    static class Rule {
        final String toolName;
        final Pattern pattern;

        Rule(String toolName, String patternGlob) {
            this.toolName = toolName;
            this.pattern = globToRegex(patternGlob);
        }

        static Rule parse(String text) {
            if (text.contains("(") && text.endsWith(")")) {
                var paren = text.indexOf('(');
                var name = text.substring(0, paren);
                var pattern = text.substring(paren + 1, text.length() - 1);
                return new Rule(canonicalName(name), pattern);
            }
            return new Rule(canonicalName(text), "");
        }

        boolean matches(String callTool, String subject) {
            if (!callTool.equalsIgnoreCase(toolName)) return false;
            if (pattern == null) return true;
            return pattern.matcher(subject).find();
        }

        static String canonicalName(String name) {
            var mapping = java.util.Map.of(
                    "Bash", "bash", "Edit", "edit_file",
                    "ReadFile", "read_file", "WriteFile", "write_file");
            return mapping.getOrDefault(name, name.toLowerCase());
        }
    }

    static class Policy {
        List<Rule> deny = List.of();
        List<Rule> ask = List.of();
        List<Rule> allow = List.of();
        List<Rule> sessionAllow = List.of();
        Decision mode = Decision.ASK;

        /** Decide a tool call against this policy. */
        Decision decide(String toolName, boolean readOnly, String subject) {
            for (var r : deny)       if (r.matches(toolName, subject)) return Decision.DENY;
            for (var r : sessionAllow) if (r.matches(toolName, subject)) return Decision.ALLOW;
            for (var r : ask)        if (r.matches(toolName, subject)) return Decision.ASK;
            for (var r : allow)      if (r.matches(toolName, subject)) return Decision.ALLOW;
            if (readOnly) return Decision.ALLOW;
            return mode;
        }

        /** 从配置的规则字符串加载 */
        static Policy fromConfig(List<String> denyRules, List<String> askRules,
                                 List<String> allowRules, Decision mode) {
            var p = new Policy();
            p.deny = rulesFrom(denyRules);
            p.ask = rulesFrom(askRules);
            p.allow = rulesFrom(allowRules);
            p.mode = mode != null ? mode : Decision.ASK;
            return p;
        }

        private static List<Rule> rulesFrom(List<String> texts) {
            if (texts == null) return List.of();
            return texts.stream().map(Rule::parse).collect(Collectors.toList());
        }
    }

    private static Pattern globToRegex(String glob) {
        if (glob == null || glob.isBlank()) return null;
        var regex = "\\Q" + glob.replace("*", "\\E.*\\Q").replace("?", "\\E.\\Q") + "\\E";
        return Pattern.compile(regex, Pattern.CASE_INSENSITIVE);
    }
}
