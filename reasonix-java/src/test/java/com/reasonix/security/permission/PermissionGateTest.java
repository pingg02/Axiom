package com.reasonix.security.permission;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

class PermissionGateTest {

    private final PermissionGate gate = new PermissionGate();

    // ── PermissionGate.decide() integration ───────────────────────────────

    @Test
    void gateDecideDeniesViaArgs() {
        assertEquals(PermissionGate.Decision.DENY,
                gate.decide("bash", false, "{\"command\":\"rm -rf /\"}"));
    }

    @Test
    void gateDecideAllowsReadOnly() {
        assertEquals(PermissionGate.Decision.ALLOW,
                gate.decide("read_file", true, "{\"path\":\"test.txt\"}"));
    }

    @Test
    void gateDecideNullToolAsks() {
        assertEquals(PermissionGate.Decision.ASK,
                gate.decide(null, false, ""));
    }

    // ── Rule parsing ──────────────────────────────────────────────────────

    @Test
    void parseSimpleRule() {
        var r = PermissionGate.Rule.parse("Bash(rm -rf *)");
        assertEquals("bash", r.toolName);
        assertNotNull(r.pattern);
    }

    @Test
    void parseToolOnlyRule() {
        var r = PermissionGate.Rule.parse("Edit");
        assertEquals("edit_file", r.toolName);
        assertNull(r.pattern);
    }

    // ── Decision priority via PermissionGate ──────────────────────────────

    @Test
    void denyWins() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of("Bash(rm *)"), List.of(), List.of("Bash(echo *)"),
                PermissionGate.Decision.ASK);
        assertEquals(PermissionGate.Decision.DENY,
                policy.decide("bash", false, "rm -rf /"));
        assertEquals(PermissionGate.Decision.ALLOW,
                policy.decide("bash", false, "echo hi"));
    }

    @Test
    void readOnlyFallsbackToAllow() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of(), List.of(), List.of(), PermissionGate.Decision.ASK);
        assertEquals(PermissionGate.Decision.ALLOW,
                policy.decide("read_file", true, "test.txt"));
    }

    @Test
    void writerFallsbackToMode() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of(), List.of(), List.of(), PermissionGate.Decision.ASK);
        assertEquals(PermissionGate.Decision.ASK,
                policy.decide("write_file", false, "test.txt"));
    }

    // ── Bash decomposition ────────────────────────────────────────────────

    @Test
    void decomposeCompoundWithAnd() {
        var parts = PermissionGate.decomposeBash("git add . && git commit -m 'x'");
        assertEquals(2, parts.size());
        assertTrue(parts.get(0).contains("git add"));
    }

    @Test
    void decomposeCompoundWithOr() {
        var parts = PermissionGate.decomposeBash("false || echo ok");
        assertEquals(2, parts.size());
        assertEquals("false", parts.get(0));
        assertEquals("echo ok", parts.get(1));
    }

    @Test
    void decomposeCompoundWithSemicolon() {
        var parts = PermissionGate.decomposeBash("echo a; echo b");
        assertEquals(2, parts.size());
    }

    @Test
    void simpleCommandNotDecomposed() {
        var parts = PermissionGate.decomposeBash("echo hello");
        assertTrue(parts.isEmpty());
    }

    @Test
    void compoundDenyWins() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of("Bash(rm *)"), List.of(), List.of("Bash(echo *)"),
                PermissionGate.Decision.ASK);
        assertEquals(PermissionGate.Decision.DENY,
                policy.decide("bash", false, "echo hi && rm -rf /"));
    }

    @Test
    void compoundAskOnMixed() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of(), List.of("Bash(git push*)"), List.of("Bash(git add *)"),
                PermissionGate.Decision.ALLOW);
        assertEquals(PermissionGate.Decision.ASK,
                policy.decide("bash", false, "git add . && git push origin"));
    }

    @Test
    void compoundReadonlyAllowed() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of(), List.of(), List.of(), PermissionGate.Decision.ASK);
        assertEquals(PermissionGate.Decision.ASK,
                policy.decide("bash", false, "echo hi && touch /tmp/x"));
    }

    // ── Read-only detection ───────────────────────────────────────────────

    @Test
    void detectReadOnlyCommands() {
        assertTrue(PermissionGate.isReadOnlyBash("echo hello"));
        assertTrue(PermissionGate.isReadOnlyBash("git status"));
        assertTrue(PermissionGate.isReadOnlyBash("ls -la /tmp"));
        assertFalse(PermissionGate.isReadOnlyBash("rm -rf /"));
        assertFalse(PermissionGate.isReadOnlyBash(""));
    }

    // ── Subject extraction ────────────────────────────────────────────────

    @Test
    void extractBashCommand() {
        assertEquals("ls -la", PermissionGate.subjectFromArgs("bash",
                "{\"command\":\"ls -la\"}"));
    }

    @Test
    void extractFilePath() {
        assertEquals("a.go", PermissionGate.subjectFromArgs("read_file",
                "{\"path\":\"a.go\"}"));
    }

    @Test
    void extractEditOldString() {
        assertEquals("foo", PermissionGate.subjectFromArgs("edit_file",
                "{\"old_string\":\"foo\"}"));
    }

    @Test
    void extractNullArgsReturnsEmpty() {
        assertEquals("", PermissionGate.subjectFromArgs("bash", null));
        assertEquals("", PermissionGate.subjectFromArgs("bash", ""));
    }

    // ── Policy fromConfig ─────────────────────────────────────────────────

    @Test
    void policyLoadsFromConfig() {
        var policy = PermissionGate.Policy.fromConfig(
                List.of("Bash(rm *)"), List.of("Bash(git push*)"),
                List.of("ReadFile"), PermissionGate.Decision.ASK);
        assertEquals(PermissionGate.Decision.DENY,
                policy.decide("bash", false, "rm -rf /"));
        assertEquals(PermissionGate.Decision.ASK,
                policy.decide("bash", false, "git push origin"));
        assertEquals(PermissionGate.Decision.ALLOW,
                policy.decide("read_file", true, "x.txt"));
    }
}
