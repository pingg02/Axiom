"""
Event sink interface — every frontend implements one Sink to consume typed events.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from reasonix.event.types import Event


class Sink(Protocol):
    """A consumer of typed events — each frontend implements one."""

    def emit(self, event: Event) -> None: ...


Callback = Callable[[Event], None]


class CallbackSink:
    """Adapter: wraps a plain callable as a Sink."""

    def __init__(self, cb: Callback) -> None:
        self._cb = cb

    def emit(self, event: Event) -> None:
        self._cb(event)


class BufferedSink:
    """Collects events in a list for testing."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)
