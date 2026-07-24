package com.reasonix.security.guardian;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class GuardianServiceTest {

    private final GuardianService service = new GuardianService();

    // ── parseVerdict ──────────────────────────────────────────────────────

    @Test
    void parseVerdictValidJson() {
        var v = service.parseVerdict(
                "{\"risk_level\":\"high\",\"user_authorization\":\"medium\"," +
                "\"outcome\":\"allow\",\"rationale\":\"user requested\"}");
        assertEquals("high", v.riskLevel());
        assertEquals("medium", v.userAuthorization());
        assertEquals("allow", v.outcome());
        assertEquals("user requested", v.rationale());
    }

    @Test
    void parseVerdictDefaultsDeny() {
        var v = service.parseVerdict("{\"outcome\":\"\"}");
        assertEquals("deny", v.outcome());
    }

    @Test
    void parseVerdictMalformedJson() {
        var v = service.parseVerdict("not json");
        assertEquals("deny", v.outcome());
        assertEquals("Guardian returned an invalid verdict", v.rationale());
    }

    @Test
    void parseVerdictMissingFields() {
        var v = service.parseVerdict("{}");
        assertEquals("unknown", v.riskLevel());
        assertEquals("deny", v.outcome());
    }

    // ── enforceHardPolicy ─────────────────────────────────────────────────

    @Test
    void hardPolicyCriticalAlwaysDeny() {
        var v = new GuardianService.GuardianVerdict("critical", "high", "allow", "");
        var result = service.enforceHardPolicy(v);
        assertEquals("deny", result.outcome());
    }

    @Test
    void hardPolicyHighLowAuthDeny() {
        var v = new GuardianService.GuardianVerdict("high", "low", "allow", "");
        var result = service.enforceHardPolicy(v);
        assertEquals("deny", result.outcome());
    }

    @Test
    void hardPolicyHighMediumAuthAllow() {
        var v = new GuardianService.GuardianVerdict("high", "medium", "allow", "");
        var result = service.enforceHardPolicy(v);
        assertEquals("allow", result.outcome());
    }

    @Test
    void hardPolicyHighHighAuthAllow() {
        var v = new GuardianService.GuardianVerdict("high", "high", "allow", "");
        var result = service.enforceHardPolicy(v);
        assertEquals("allow", result.outcome());
    }

    @Test
    void hardPolicyLowAllow() {
        var v = new GuardianService.GuardianVerdict("low", "unknown", "allow", "");
        var result = service.enforceHardPolicy(v);
        assertEquals("allow", result.outcome());
    }

    @Test
    void hardPolicyUnknownRiskDefaultsUnknown() {
        var v = new GuardianService.GuardianVerdict("unknown", "unknown", "allow", "");
        var result = service.enforceHardPolicy(v);
        assertEquals("allow", result.outcome());
    }

    // ── ruleBasedCheck ────────────────────────────────────────────────────

    @Test
    void ruleBasedCheckBlocksRmRf() {
        var result = service.ruleBasedCheck("bash", "rm -rf /");
        assertEquals("deny", result);
    }

    @Test
    void ruleBasedCheckBlocksRmRfStar() {
        var result = service.ruleBasedCheck("bash", "rm -rf /*");
        assertEquals("deny", result);
    }

    @Test
    void ruleBasedCheckBlocksGitPushForce() {
        var result = service.ruleBasedCheck("bash", "git push --force origin");
        assertEquals("deny", result);
    }

    @Test
    void ruleBasedCheckBlocksGitPushF() {
        var result = service.ruleBasedCheck("bash", "git push -f origin");
        assertEquals("deny", result);
    }

    @Test
    void ruleBasedCheckBlocksEtcShadow() {
        var result = service.ruleBasedCheck("bash", "cat /etc/shadow");
        assertEquals("deny", result);
    }

    @Test
    void ruleBasedCheckAllowsSafeCommand() {
        var result = service.ruleBasedCheck("bash", "echo hello");
        assertNull(result);
    }

    @Test
    void ruleBasedCheckNullArgsReturnsNull() {
        var result = service.ruleBasedCheck("bash", null);
        assertNull(result);
    }

    // ── TranscriptCursor ──────────────────────────────────────────────────

    @Test
    void transcriptCursorFirstDelta() {
        var cursor = new TranscriptCursor();
        var delta = cursor.delta("[\"msg1\",\"msg2\"]");
        assertTrue(delta.contains("TRANSCRIPT DELTA (2 new)"));
        assertEquals(2, cursor.getEntryCount());
    }

    @Test
    void transcriptCursorNoNewEntries() {
        var cursor = new TranscriptCursor();
        cursor.delta("[\"msg1\"]");
        var delta = cursor.delta("[\"msg1\"]");
        assertTrue(delta.contains("no new entries"));
    }

    @Test
    void transcriptCursorMalformedJson() {
        var cursor = new TranscriptCursor();
        var delta = cursor.delta("not json");
        // Should fall through gracefully
        assertNotNull(delta);
    }
}
