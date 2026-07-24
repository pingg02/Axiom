"""Phase 2 tests — permission gate, guardian, secrets, evidence."""

import asyncio

from reasonix.evidence import Ledger, Receipt
from reasonix.guardian.guardian import (
    CircuitBreaker,
    GuardianVerdict,
    TranscriptCursor,
)
from reasonix.permission.permission import (
    Decision,
    Gate,
    Policy,
    Rule,
    _decompose_bash,
    _is_readonly_command,
)
from reasonix.provider import Message, Role
from reasonix.secrets.redact import RedactHandler, mask

# ── Permission tests ────────────────────────────────────────────────────

def test_rule_parsing():
    r = Rule.parse("Bash(rm -rf *)")
    assert r.tool_name == "bash"  # canonicalized to lowercase
    assert r.pattern == "rm -rf *"

    r2 = Rule.parse("Edit")
    assert r2.tool_name == "edit_file"
    assert r2.pattern == ""


def test_rule_matching():
    r = Rule.parse("Bash(rm -rf *)")
    assert r.matches("bash", "rm -rf /var")

    r2 = Rule.parse("Edit")
    assert r2.matches("edit_file", "some/path")


def test_policy_deny_wins():
    policy = Policy(
        mode=Decision.ASK,
        deny=[Rule.parse("Bash(rm *)")],
        allow=[Rule.parse("Bash(echo *)")],
    )
    assert policy.decide("bash", False, '{"command":"rm -rf /"}') == Decision.DENY
    assert policy.decide("bash", False, '{"command":"echo hello"}') == Decision.ALLOW


def test_policy_readonly_fallback():
    policy = Policy(mode=Decision.ASK)
    assert policy.decide("read_file", True, '{"path":"test.txt"}') == Decision.ALLOW


def test_policy_writer_fallback():
    policy = Policy(mode=Decision.ASK)
    assert policy.decide("write_file", False, '{"path":"test.txt"}') == Decision.ASK


def test_gate_denies_ask_without_interactive_approver():
    policy = Policy(mode=Decision.ASK)

    allowed, reason = asyncio.run(
        Gate(policy).check("write_file", '{"path":"test.txt"}', read_only=False)
    )

    assert allowed is False
    assert reason == "approval required but no approver is configured"


def test_bash_decompose():
    parts = _decompose_bash("git add . && git commit -m 'x' && git push")
    assert len(parts) == 3
    assert "git add ." in parts
    assert "git commit -m 'x'" in parts


def test_readonly_detection():
    assert _is_readonly_command("echo hello")
    assert _is_readonly_command("git status")
    assert not _is_readonly_command("rm -rf /")


def test_session_allow():
    policy = Policy(
        mode=Decision.ASK,
        deny=[Rule.parse("Bash(rm /etc*)")],
        session_allow=[Rule.parse("Bash(rm /safe*)")],
    )
    assert policy.decide("bash", False, '{"command":"rm /safe/test"}') == Decision.ALLOW
    assert policy.decide("bash", False, '{"command":"rm /etc/passwd"}') == Decision.DENY


def test_session_allow_overrides_ask():
    policy = Policy(
        mode=Decision.ASK,
        ask=[Rule.parse("Bash(git push*)")],
        session_allow=[Rule.parse("Bash(git push /safe*)")],
    )
    assert policy.decide("bash", False, '{"command":"git push /safe/branch"}') == Decision.ALLOW
    assert policy.decide("bash", False, '{"command":"git push /other"}') == Decision.ASK


def test_bash_compound_deny_wins():
    policy = Policy(mode=Decision.ASK, deny=[Rule.parse("Bash(rm *)")])
    assert policy.decide("bash", False, '{"command":"echo hi && rm -rf /"}') == Decision.DENY


def test_bash_compound_ask_wins():
    policy = Policy(mode=Decision.ALLOW, ask=[Rule.parse("Bash(git push*)")])
    d = policy.decide("bash", False, '{"command":"git add . && git push origin"}')
    assert d == Decision.ASK


def test_bash_compound_readonly_allowed():
    policy = Policy(mode=Decision.ASK)
    d = policy.decide("bash", False, '{"command":"echo hi && touch /tmp/x"}')
    assert d == Decision.ASK  # write segment needs ask


# ── Circuit Breaker tests ────────────────────────────────────────────────

def test_cb_starts_closed():
    cb = CircuitBreaker()
    assert not cb.tripped


def test_cb_3_consecutive_trips():
    cb = CircuitBreaker()
    assert not cb.record_denial()
    assert not cb.record_denial()
    assert cb.record_denial()      # 3rd consecutive trips
    assert not cb.record_denial()  # already tripped


def test_cb_allow_resets_consecutive():
    cb = CircuitBreaker()
    cb.record_denial()
    cb.record_denial()
    cb.record_allow()
    assert not cb.record_denial()


def test_cb_reset_turn():
    cb = CircuitBreaker()
    cb.record_denial()
    cb.record_denial()
    cb.record_denial()
    assert cb.tripped
    cb.reset_turn()
    assert not cb.tripped
    assert cb.consecutive_denials == 0
    assert len(cb.recent_denials) == 0


def test_cb_recent_window_trips():
    cb = CircuitBreaker()
    for _ in range(9):
        cb.record_denial()
        cb.record_allow()
    cb.record_allow()
    assert cb.record_denial()
    assert cb.tripped


# ── Guardian Verdict tests ──────────────────────────────────────────────

def test_verdict_parses_json():
    v = GuardianVerdict.from_json(
        '{"risk_level":"high","user_authorization":"low","outcome":"allow","rationale":"test"}'
    )
    assert v.risk_level == "high"
    assert v.outcome == "allow"


def test_verdict_hard_policy_critical():
    v = GuardianVerdict(risk_level="critical", outcome="allow")
    v.enforce_hard_policy()
    assert v.outcome == "deny"


def test_verdict_hard_policy_high_low_auth():
    v = GuardianVerdict(risk_level="high", user_authorization="low", outcome="allow")
    v.enforce_hard_policy()
    assert v.outcome == "deny"


def test_verdict_hard_policy_high_high_auth():
    v = GuardianVerdict(risk_level="high", user_authorization="high", outcome="allow")
    v.enforce_hard_policy()
    assert v.outcome == "allow"


def test_verdict_parse_error_defaults_deny():
    v = GuardianVerdict.from_json("not json")
    assert v.outcome == "deny"
    assert "failed to parse" in v.rationale


# ── Transcript Cursor tests ─────────────────────────────────────────────

def test_cursor_delta():
    cursor = TranscriptCursor()
    msgs = [Message(role=Role.USER, content="hello"),
            Message(role=Role.ASSISTANT, content="hi")]
    delta = cursor.delta(msgs)
    assert "TRANSCRIPT DELTA (2 new)" in delta
    assert cursor.entry_count == 2
    delta2 = cursor.delta(msgs)
    assert "no new entries" in delta2


# ── Secrets Redaction tests ─────────────────────────────────────────────

def test_mask_short():
    assert mask("abc") == "[redacted]"


def test_mask_sk_prefix():
    result = mask("sk-proj-abc123def456")
    assert result.startswith("sk-")
    assert "*" in result


def test_mask_boundary_values():
    assert mask("123456789012") == "[redacted]"      # len=12
    result = mask("1234567890abc")                    # len=13
    assert result.startswith("1234")
    assert result.endswith("0abc")
    result = mask("sk-abcdefgh123")                   # sk-prefix len=13
    assert result.startswith("sk-ab")
    assert mask("ab") == "[redacted]"                  # too short


def test_redact_openai_key():
    h = RedactHandler()
    result = h.redact("api key is sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz")
    assert "[redacted]" in result or "*" in result
    assert "sk-proj" not in result


def test_redact_jwt():
    h = RedactHandler()
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNqP"
    result = h.redact(f"token = {jwt}")
    assert "[redacted]" in result or "*" in result
    assert "eyJhbGci" not in result


def test_redact_env_filter():
    h = RedactHandler()
    env = {"PATH": "/usr/bin", "DB_PASSWORD": "supersecret", "HOME": "/home/user"}
    filtered = h.filter_env(env)
    assert filtered["PATH"] == "/usr/bin"
    assert filtered["DB_PASSWORD"] == "[redacted]"
    assert filtered["HOME"] == "/home/user"


def test_redact_tool_output_disabled():
    h = RedactHandler(redact_tool_output=False)
    assert h.redact_tool_result("my key is sk-proj-abc") == "my key is sk-proj-abc"


# ── Evidence Ledger tests ────────────────────────────────────────────────

def test_ledger_write_read_cycle():
    ledger = Ledger()
    ledger.record(Receipt(tool_name="write_file", args='{"path":"a.go"}',
                          success=True, write=True, paths=["a.go"]))
    idx, found = ledger.latest_write_index(["a.go"])
    assert found
    assert idx == 0


def test_ledger_stale_anchor_blocks():
    ledger = Ledger()
    ledger.record(Receipt(tool_name="write_file", args='{"path":"a.go"}',
                          success=True, write=True, paths=["a.go"]))
    msg = ledger.stale_anchor_edit_blocked("edit_file", '{"path":"a.go"}')
    assert msg is not None
    assert "fresh read required" in msg


def test_ledger_anchor_refresh_unblocks():
    ledger = Ledger()
    ledger.record(Receipt(tool_name="write_file", args='{"path":"a.go"}',
                          success=True, write=True, paths=["a.go"]))
    ledger.record(Receipt(tool_name="read_file", args='{"path":"a.go"}',
                          success=True, read=True, paths=["a.go"]))
    msg = ledger.stale_anchor_edit_blocked("edit_file", '{"path":"a.go"}')
    assert msg is None


def test_ledger_windowed_read_not_enough():
    ledger = Ledger()
    ledger.record(Receipt(tool_name="write_file", args='{"path":"a.go"}',
                          success=True, write=True, paths=["a.go"]))
    ledger.record(Receipt(tool_name="read_file", args='{"path":"a.go","offset":0}',
                          success=True, read=True, paths=["a.go"]))
    msg = ledger.stale_anchor_edit_blocked("edit_file", '{"path":"a.go"}')
    assert msg is not None


def test_stale_anchor_non_edit_not_blocked():
    ledger = Ledger()
    assert ledger.stale_anchor_edit_blocked("read_file", '{"path":"a.go"}') is None


def test_stale_anchor_empty_path_not_blocked():
    ledger = Ledger()
    assert ledger.stale_anchor_edit_blocked("edit_file", "{}") is None


def test_stale_anchor_bad_json_not_blocked():
    ledger = Ledger()
    assert ledger.stale_anchor_edit_blocked("edit_file", "not json") is None
