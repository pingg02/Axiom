"""
Tool abstraction — each tool implements this interface.

Built-in tools live in tool/builtin/; registry lives in tool/registry.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from reasonix.diff import Change


class Tool(ABC):
    """A capability the model can invoke."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def schema(self) -> dict[str, Any]:
        """JSON Schema for parameters."""

    @abstractmethod
    async def execute(self, args_json: str) -> str:
        """Execute with deserialized args, return result text."""

    @property
    def read_only(self) -> bool:
        """True if the tool has no observable side effects."""
        return False

    async def preview(self, args_json: str) -> Change | None:
        """Optional: preview what change this call *would* make."""
        return None
