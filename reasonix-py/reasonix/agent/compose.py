"""
System prompt composition with cache-first prefix management.

DeepSeek's automatic prefix caching means the *byte-exact* start of
every turn's system prompt must stay stable across turns. Compose()
guarantees this by keeping the prefix segment (base + tools + memory)
byte-identical on every call with the same registry/memory.
"""

from __future__ import annotations

import datetime
import platform
from dataclasses import dataclass

from reasonix.memory import MemorySet
from reasonix.tool.registry import RegistrySnapshot

# ── The cache-stable prefix ──────────────────────────────────────────────

BASE_PROMPT = """\
You are Reasonix, a coding agent.
Use the available tools when they help you complete the user's request.
Keep changes focused and responses concise.

User-owned choices: when a consequential decision has no safe, obvious default, call the ask tool so the user can choose. Otherwise proceed with a sensible reversible default. Do not ask in prose when ask is available. In non-interactive runs, state the assumption and take the safest reversible path.

Reply in the same language the user is using in their most recent message: if they write in Chinese answer in Chinese, in English answer in English, and switch whenever they switch. Let this also guide the language you think in. Always keep code, identifiers, file paths, shell commands, and technical terms in their original form — never translate them."""


def _os_string() -> str:
    s = platform.system().lower()
    if s.startswith("win"):
        return "windows/amd64"
    if s == "darwin":
        return "darwin/amd64"
    return "linux/amd64"


def _shell_string() -> str:
    if platform.system().lower().startswith("win"):
        return "powershell"
    return "bash"


def _format_tools_block(snapshot: RegistrySnapshot) -> str:
    lines = [f"- {t.name} — {t.description}" for t in snapshot.all()]
    return "\n".join(sorted(lines))


def _format_memory_block(memory: MemorySet | None) -> str:
    if not memory:
        return "(no memory loaded)"
    parts: list[str] = []
    for doc in memory.docs:
        parts.append(f"--- {doc.source} ---")
        parts.append(doc.content)
        parts.append("")
    if memory.index:
        parts.append("## Saved memories")
        parts.append(memory.index)
    return "\n".join(parts)


@dataclass
class ComposeInput:
    """Everything needed to compose one system prompt."""

    registry_snapshot: RegistrySnapshot
    memory: MemorySet | None = None
    instructions: str = ""
    additional_prompt: str = ""
    output_style: str = ""
    language: str = ""
    plan_mode: bool = False


def compose_prefix(inp: ComposeInput) -> str:
    """Build only the cache-stable prefix (base + tools + memory).

    This output MUST be byte-identical on every call with the same
    registry_snapshot and memory — tools and memory change only
    between sessions, not between turns within a session.
    """
    tools_block = _format_tools_block(inp.registry_snapshot)
    memory_block = _format_memory_block(inp.memory)

    env = f"""\
## Environment

- OS: {_os_string()}
- Shell: {_shell_string()}

## Tools

{tools_block}

## Memory

{memory_block}"""

    return f"{BASE_PROMPT}\n\n{env}"


@dataclass
class CacheState:
    """Immutable cache state for prefix reuse."""

    key: tuple[RegistrySnapshot, MemorySet | None]
    prefix: str


_cache: CacheState | None = None


def compose_system_prompt(inp: ComposeInput) -> str:
    """Assemble the full system prompt with cached prefix.

    The prefix (base + tools + memory) is reused across turns as long
    as the registry and memory haven't changed. Only the turn-specific
    tail changes between turns, keeping the prefix cache-stable.
    """
    global _cache

    key = (inp.registry_snapshot, inp.memory)

    # Rebuild prefix only when registry or memory changes
    if _cache is None or _cache.key != key:
        prefix = compose_prefix(inp)
        _cache = CacheState(key=key, prefix=prefix)
    else:
        prefix = _cache.prefix

    # Build the turn-specific tail
    tail_parts: list[str] = []

    if inp.plan_mode:
        tail_parts.append(
            "## Plan mode\n"
            "You are in read-only planning mode. Investigate the problem, "
            "explore the codebase, and propose a plan. Do NOT make changes."
        )
    if inp.instructions:
        tail_parts.append(f"## Instructions\n{inp.instructions}")
    if inp.additional_prompt:
        tail_parts.append(inp.additional_prompt)
    if inp.language:
        tail_parts.append(
            f"This session's UI language is {inp.language}. "
            "Reply in the UI language by default."
        )
    tail_parts.append(f"Today's date: {datetime.date.today().isoformat()}")

    return f"{prefix}\n\n" + "\n\n".join(tail_parts)
