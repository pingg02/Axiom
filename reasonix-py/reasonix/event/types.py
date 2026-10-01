"""
Event types — the typed event stream that decouples
"what happened" from "how to show it".
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from reasonix.diff import Change


class Kind(IntEnum):
    """Tag for every event emitted during a turn."""

    TURN_STARTED = 0
    REASONING = 1
    TEXT = 2
    MESSAGE = 3
    TOOL_DISPATCH = 4
    TOOL_RESULT = 5
    USAGE = 6
    NOTICE = 7
    PHASE = 8
    APPROVAL_REQUEST = 9
    ASK_REQUEST = 10
    TURN_DONE = 11
    ERROR = 12
    HISTORY_COMMITTED = 13


@dataclass
class ToolCallInfo:
    """Metadata about a tool call for dispatch/result events."""
    id: str
    name: str
    args_json: str
    read_only: bool = False
    output: str = ""
    error: str | None = None
    truncated: bool = False
    change: Change | None = None


@dataclass
class UsageInfo:
    """Token usage telemetry."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ApprovalRequest:
    """A tool call pending human approval."""
    id: str
    tool_name: str
    subject: str
    args_json: str


@dataclass
class AskQuestion:
    """An interactive question for the user."""
    header: str
    question: str
    options: list[str]
    multi_select: bool = False


@dataclass
class AskAnswer:
    """User's response to an AskQuestion."""
    values: list[str]


@dataclass
class Event:
    """One typed event in the stream — the core data unit for frontend rendering."""

    kind: Kind
    text: str = ""
    reasoning: str = ""
    tool: ToolCallInfo | None = None
    usage: UsageInfo | None = None
    approval: ApprovalRequest | None = None
    ask_id: str = ""
    ask_questions: list[AskQuestion] | None = None
    level: str = "info"
    phase_label: str = ""
    error: str = ""


def event_to_frontend_dict(event: Event) -> dict[str, Any]:
    """Convert an Event into the shared JSON shape used by every frontend."""
    data: dict[str, Any] = {
        "kind": event.kind.name.lower(),
        "text": event.text,
        "reasoning": event.reasoning,
        "error": event.error,
        "level": event.level,
        "phase_label": event.phase_label,
    }

    if event.tool:
        data["tool"] = {
            "id": event.tool.id,
            "name": event.tool.name,
            "args_json": event.tool.args_json,
            "read_only": event.tool.read_only,
            "output": event.tool.output,
            "error": event.tool.error,
            "truncated": event.tool.truncated,
        }
        if event.tool.change:
            data["tool"]["change"] = {
                "path": event.tool.change.path,
                "description": event.tool.change.description,
                "unified_diff": event.tool.change.unified_diff,
                "added": event.tool.change.added,
                "removed": event.tool.change.removed,
            }

    if event.usage:
        data["usage"] = {
            "input_tokens": event.usage.input_tokens,
            "output_tokens": event.usage.output_tokens,
            "cache_read_tokens": event.usage.cache_read_tokens,
            "cache_write_tokens": event.usage.cache_write_tokens,
            "cost_usd": event.usage.cost_usd,
        }

    if event.approval:
        data["approval"] = {
            "id": event.approval.id,
            "tool_name": event.approval.tool_name,
            "subject": event.approval.subject,
            "args_json": event.approval.args_json,
        }

    if event.ask_id:
        data["ask_id"] = event.ask_id

    if event.ask_questions:
        data["ask_questions"] = [
            {
                "header": q.header,
                "question": q.question,
                "options": q.options,
                "multi_select": q.multi_select,
            }
            for q in event.ask_questions
        ]

    return data
