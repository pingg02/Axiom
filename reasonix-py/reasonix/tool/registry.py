"""
Tool registry — mutable registry and immutable snapshot.

Registry is built before each session; its snapshot is passed to the agent
run loop for read-only access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reasonix.tool.base import Tool


@dataclass
class RegistrySnapshot:
    """Immutable snapshot for the agent run loop."""

    tools: dict[str, Tool] = field(default_factory=dict)

    def by_name(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def all(self) -> list[Tool]:
        return list(self.tools.values())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Serialize tools to OpenAI-compatible tool definitions."""
        result = []
        for t in self.tools.values():
            result.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            })
        return result

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Serialize tools to Anthropic-compatible format."""
        result = []
        for t in self.tools.values():
            result.append({
                "name": t.name,
                "description": t.description,
                "input_schema": t.schema,
            })
        return result


class Registry:
    """Mutable registry — built before each session from config."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        key = tool.name
        if key in self._tools:
            raise ValueError(f"Duplicate tool name: {key}")
        self._tools[key] = tool

    def remove(self, name: str) -> None:
        self._tools.pop(name, None)

    def snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(tools=dict(self._tools))
