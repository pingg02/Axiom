"""
Provider abstract interface and global factory registry.

Each provider subclass registers itself via register_provider() so the
boot factory can discover it by kind ("openai", "anthropic", ...).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from reasonix.provider.base import Message, StreamEvent, Usage


@dataclass
class ProviderConfig:
    """Resolved configuration for one provider entry."""

    kind: str
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    models: list[str] = field(default_factory=list)


class Provider(ABC):
    """Abstract model backend — each provider kind implements generate + generate_stream."""

    @classmethod
    def from_config(cls, config: ProviderConfig) -> Provider:
        """Build a provider instance from resolved configuration."""
        raise NotImplementedError(f"{cls.__name__} does not implement from_config()")

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[Message, Usage]:
        """Non-streaming generation."""

    @abstractmethod
    def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming generation — yields chunks as they arrive."""

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @property
    def supports_streaming(self) -> bool:
        return True


# Global factory registry — populated by register_provider() at import time.
ProviderFactory = type[Provider]
PROVIDER_FACTORIES: dict[str, ProviderFactory] = {}


def register_provider(kind: str, cls: type[Provider]) -> None:
    """Register a provider class so boot can find it by kind."""
    PROVIDER_FACTORIES[kind] = cls
