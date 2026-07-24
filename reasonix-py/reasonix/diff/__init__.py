"""
Diff utilities — Change dataclass for tool preview support.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass


@dataclass
class Change:
    """A proposed file change, produced by tool.preview()."""
    path: str
    old_content: str | None = None
    new_content: str | None = None
    description: str = ""
    unified_diff: str = ""
    added: int = 0
    removed: int = 0


def build_change(
    path: str,
    old_content: str | None,
    new_content: str | None,
    description: str = "",
) -> Change:
    """Build a display-ready text change with stable line statistics."""
    old_lines = (old_content or "").splitlines(keepends=True)
    new_lines = (new_content or "").splitlines(keepends=True)
    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="\n",
        )
    )
    added = sum(
        1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
    )
    removed = sum(
        1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
    )
    return Change(
        path=path,
        old_content=old_content,
        new_content=new_content,
        description=description,
        unified_diff="".join(diff_lines),
        added=added,
        removed=removed,
    )


__all__ = ["Change", "build_change"]
