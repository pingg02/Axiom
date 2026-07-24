"""
Memory system — hierarchical document discovery and auto-memory storage.

MemorySet holds the documents and index loaded into the system prompt.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MemoryDoc:
    """One loaded memory document (REASONIX.md, MEMORY.md, etc.)."""
    source: str  # file path or identifier
    content: str
    mtime: float = 0.0


@dataclass
class MemorySet:
    """Collection of memory documents assembled for one session."""

    docs: list[MemoryDoc] = field(default_factory=list)
    index: str = ""

    def add(self, doc: MemoryDoc) -> None:
        self.docs.append(doc)

    @property
    def text(self) -> str:
        """Concatenated memory text for system prompt injection."""
        parts = []
        for doc in self.docs:
            parts.append(f"--- {doc.source} ---")
            parts.append(doc.content)
        return "\n\n".join(parts)

    @classmethod
    def empty(cls) -> MemorySet:
        return cls()


class MemoryLoader:
    """Discover and load memory documents from the filesystem.

    Resolution order: project REASONIX.md > local REASONIX.local.md >
    user-level ~/.config/reasonix/REASONIX.md > ancestor dirs.
    """

    def __init__(self, project_root: str | Path = "."):
        self.project_root = Path(project_root).resolve()

    def load(self) -> MemorySet:
        mem = MemorySet()

        # 1. Project-level REASONIX.md
        for name in ("REASONIX.md", "AGENTS.md"):
            candidate = self.project_root / name
            if candidate.is_file():
                mem.add(MemoryDoc(
                    source=str(candidate),
                    content=candidate.read_text(encoding="utf-8"),
                    mtime=candidate.stat().st_mtime,
                ))
                break

        # 2. Local overrides (git-ignored)
        local_file = self.project_root / "REASONIX.local.md"
        if local_file.is_file():
            mem.add(MemoryDoc(
                source=str(local_file),
                content=local_file.read_text(encoding="utf-8"),
                mtime=local_file.stat().st_mtime,
            ))

        # 3. User-level config
        if os.name == "nt":
            user_dir = Path(os.environ.get("APPDATA", "~/.config"))
        else:
            user_dir = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config"))
        user_file = user_dir.expanduser() / "reasonix" / "REASONIX.md"
        if user_file.is_file():
            mem.add(MemoryDoc(
                source=str(user_file),
                content=user_file.read_text(encoding="utf-8"),
                mtime=user_file.stat().st_mtime,
            ))

        return mem


class MemoryStore:
    """Auto-memory persistence — save/load durable facts.

    Facts are stored as frontmatter Markdown files in a per-project
    memory directory.
    """

    def __init__(self, storage_dir: str | Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, content: str, description: str = "") -> Path:
        """Save a memory fact."""
        path = self.storage_dir / f"{name}.md"
        parts = []
        if description:
            parts.append("---")
            parts.append(f"description: {description}")
            parts.append("---")
            parts.append("")
        parts.append(content)
        path.write_text("\n".join(parts), encoding="utf-8")
        return path

    def load(self, name: str) -> MemoryDoc | None:
        """Load a memory fact by name."""
        path = self.storage_dir / f"{name}.md"
        if not path.is_file():
            return None
        return MemoryDoc(
            source=str(path),
            content=path.read_text(encoding="utf-8"),
            mtime=path.stat().st_mtime,
        )

    def list_names(self) -> list[str]:
        """List all saved memory fact names."""
        return sorted(p.stem for p in self.storage_dir.glob("*.md") if p.is_file())
