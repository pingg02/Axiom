"""
Permission gate — the Allow/Ask/Deny three-level decision system.

Pure rule evaluation (no I/O). A Gate wraps a Policy with an optional
Approver and is what the agent consults at execute time.
"""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Decision(Enum):
    """Outcome of evaluating a tool call against a Policy."""
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ApprovalScope(Enum):
    """How long an interactive approval should remain effective."""

    ONCE = "once"
    SESSION = "session"
    ALWAYS = "always"


# ── Complete canonical name mapping ─────────────────────────────────────

_CANONICAL_MAP = {
    "Bash": "bash",
    "Edit": "edit_file",
    "ReadFile": "read_file",
    "WriteFile": "write_file",
    "DeleteRange": "delete_range",
    "NotebookEdit": "notebook_edit",
    "MoveFile": "move_file",
    "Glob": "glob",
    "Grep": "grep",
    "WebFetch": "web_fetch",
    "Task": "task",
    "Ask": "ask",
    "Remember": "remember",
    "Forget": "forget",
    "CompleteStep": "complete_step",
    "TodoWrite": "todo_write",
}


def canonical_name(rule_tool: str) -> str:
    """Map a rule shorthand (e.g. 'Bash') to actual tool name (e.g. 'bash')."""
    return _CANONICAL_MAP.get(rule_tool, rule_tool.lower())


@dataclass
class Rule:
    """A permission rule: tool_name(optional_glob_pattern).

    Examples:
        Bash(rm -rf *)     → match bash tool, args containing 'rm -rf'
        Edit               → match edit_file (any args)
    """

    tool_name: str
    pattern: str = ""

    @classmethod
    def parse(cls, text: str) -> Rule:
        """Parse 'ToolName(pattern)' or 'ToolName'."""
        if "(" in text and text.endswith(")"):
            name, rest = text.split("(", 1)
            return cls(tool_name=canonical_name(name.strip()),
                       pattern=rest.rstrip(")").strip())
        return cls(tool_name=canonical_name(text.strip()))

    def matches(self, tool_name: str, subject: str) -> bool:
        """Check if this rule matches a tool call."""
        if self.tool_name != tool_name:
            return False
        if not self.pattern:
            return True
        return _glob_match(self.pattern, subject)


def _glob_match(pattern: str, subject: str) -> bool:
    """Simple glob-style matching (supports * and ?)."""
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return bool(re.match(f"^{regex}$", subject, re.IGNORECASE))


def _subject_from_args(tool_name: str, args_json: str) -> list[str]:
    """Extract subject(s) from tool arguments.

    Returns a list — most tools return [path_or_command], but move_file
    returns [source, destination] for two-endpoint protection.
    """
    tool = tool_name.lower()
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        return [args_json]

    if tool == "bash":
        return [args.get("command", "")]
    if tool in ("read_file", "write_file", "edit_file", "delete_range", "notebook_edit"):
        return [args.get("path", args.get("old_string", ""))]
    if tool == "move_file":
        return [args.get("source_path", ""), args.get("destination_path", "")]
    if tool in ("grep", "glob"):
        return [args.get("pattern", "")]
    return [args_json]


@dataclass
class Policy:
    """Permission policy — set of allow/ask/deny rules.

    Precedence: Deny > SessionAllow > Ask > Allow > readOnly_fallback(Allow) > writer_fallback(Mode)

    decide() accepts a list of subjects from _subject_from_args and evaluates
    each one. All subjects must pass for the call to be allowed.
    """

    mode: Decision = Decision.ASK
    deny: list[Rule] = field(default_factory=list)
    ask: list[Rule] = field(default_factory=list)
    allow: list[Rule] = field(default_factory=list)
    session_allow: list[Rule] = field(default_factory=list)

    def decide(self, tool_name: str, read_only: bool, args_json: str = "") -> Decision:
        """Evaluate a tool call against this policy."""
        subjects = _subject_from_args(tool_name, args_json)

        # Bash compound command decomposition
        if tool_name == "bash" and subjects:
            return self._decide_bash(read_only, subjects[0])

        # Evaluate each subject — all must pass
        outcome = Decision.ALLOW
        for subject in subjects:
            d = self._decide_subject(tool_name, read_only, subject)
            if d == Decision.DENY:
                return Decision.DENY
            if d == Decision.ASK:
                outcome = Decision.ASK
        return outcome

    def _decide_subject(self, tool_name: str, read_only: bool, subject: str) -> Decision:
        """Core precedence: Deny > SessionAllow > Ask > Allow > fallback."""
        for rule in self.deny:
            if rule.matches(tool_name, subject):
                return Decision.DENY
        for rule in self.session_allow:
            if rule.matches(tool_name, subject):
                return Decision.ALLOW
        for rule in self.ask:
            if rule.matches(tool_name, subject):
                return Decision.ASK
        for rule in self.allow:
            if rule.matches(tool_name, subject):
                return Decision.ALLOW
        if read_only:
            return Decision.ALLOW
        return self.mode

    def _decide_bash(self, read_only: bool, command: str) -> Decision:
        """Decompose compound bash commands, evaluate each segment."""
        if _is_compound(command):
            segments = _decompose_bash(command)
            outcome = Decision.ALLOW
            for seg in segments:
                seg_readonly = read_only or _is_readonly_command(seg)
                d = self._decide_subject("bash", seg_readonly, seg.strip())
                if d == Decision.DENY:
                    return Decision.DENY
                if d == Decision.ASK:
                    outcome = Decision.ASK
            return outcome
        return self._decide_subject("bash", read_only, command)


class Approver(Protocol):
    """Protocol for interactive approval (human or guardian)."""

    async def approve(
        self, tool_name: str, subject: str, args_json: str
    ) -> tuple[bool, ApprovalScope]:
        """Return whether the call is allowed and the grant scope."""


@dataclass
class Gate:
    """Permission gate — policy + optional interactive approver."""

    policy: Policy
    approver: Approver | None = None
    on_remember: Callable[[str], None] | None = None

    async def check(self, tool_name: str, args_json: str,
                    read_only: bool = False) -> tuple[bool, str]:
        """Check a tool call against policy. Returns (allowed, reason)."""
        decision = self.policy.decide(tool_name, read_only, args_json)

        if decision == Decision.DENY:
            return False, "denied by permission policy"
        if decision == Decision.ALLOW:
            return True, ""

        if self.approver is None:
            return False, "approval required but no approver is configured"

        subjects = _subject_from_args(tool_name, args_json)
        subject_str = ", ".join(subjects)
        allowed, scope = await self.approver.approve(tool_name, subject_str, args_json)

        if allowed and scope in (ApprovalScope.SESSION, ApprovalScope.ALWAYS):
            rule = _approval_grouping_rule(tool_name, subjects)
            target = (
                self.policy.allow
                if scope == ApprovalScope.ALWAYS
                else self.policy.session_allow
            )
            if rule not in target:
                target.append(rule)
            if scope == ApprovalScope.ALWAYS and self.on_remember:
                self.on_remember(_format_rule(rule))

        return allowed, "" if allowed else "denied by user"


def _approval_grouping_rule(tool_name: str, subjects: list[str]) -> Rule:
    """Build a session-safe grouping rule instead of granting every future call."""
    subject = subjects[0].strip() if subjects else ""
    if tool_name == "bash" and subject:
        try:
            tokens = shlex.split(subject)
        except ValueError:
            tokens = []
        prefix = " ".join(tokens[:2])
        return Rule(tool_name=tool_name, pattern=f"{prefix}*" if prefix else subject)
    if tool_name in {
        "read_file",
        "write_file",
        "edit_file",
        "delete_range",
        "notebook_edit",
        "move_file",
    } and subject:
        normalized = subject.replace("\\", "/")
        parent, separator, _ = normalized.rpartition("/")
        if separator and parent:
            return Rule(tool_name=tool_name, pattern=f"{parent}/*")
        return Rule(tool_name=tool_name, pattern=normalized)
    return Rule(tool_name=tool_name)


def _format_rule(rule: Rule) -> str:
    return (
        f"{rule.tool_name}({rule.pattern})"
        if rule.pattern
        else rule.tool_name
    )


# ── Helper functions ──────────────────────────────────────────────────────

def _is_compound(command: str) -> bool:
    return bool(re.search(r'\s*(?:&&|\|\||;)\s*', command))


def _decompose_bash(command: str) -> list[str]:
    parts = re.split(r'\s*(&&|\|\||;)\s*', command)
    return [p.strip() for p in parts if p.strip() and p.strip() not in ("&&", "||", ";")]


def _is_readonly_command(command: str) -> bool:
    """Check if a bash command is read-only."""
    readonly_commands = {
        "echo", "ls", "cat", "head", "tail", "grep", "find",
        "git status", "git diff", "git log", "git show", "git branch",
        "pwd", "which", "whoami", "date", "env", "printenv",
    }
    try:
        first_word = shlex.split(command)[0] if command else ""
    except (ValueError, IndexError):
        return False  # Malformed command — treat as not read-only (safe default)
    for cmd in readonly_commands:
        if command.strip().startswith(cmd):
            return True
    return first_word in readonly_commands
