"""
Provider data types — message formats, roles, and streaming event types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class ToolCall:
    """A tool call emitted by the model."""
    id: str
    name: str
    args_json: str


@dataclass
class MemoryCitation:
    """A citation to a local memory document."""
    id: str = ""
    source: str = ""
    line_start: int = 0
    line_end: int = 0
    note: str = ""
    kind: str = ""


@dataclass
class Message:
    """One message in the conversation history."""

    role: Role
    content: str = ""
    images: list[str] = field(default_factory=list)
    reasoning_content: str = ""
    reasoning_signature: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    name: str = ""
    memory_citations: list[MemoryCitation] = field(default_factory=list)
    work_duration_ms: int = 0
    edited: bool = False
    original: str = ""


@dataclass
class Usage:
    """Token usage for one generation."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class StreamEvent:
    """One chunk from a streaming generation."""

    delta_text: str = ""
    delta_reasoning: str = ""
    tool_calls: list[ToolCall] | None = None
    finish_reason: str = ""
    usage: Usage | None = None
    message: Message | None = None
