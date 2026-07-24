"""
Built-in tool: grep — search files for regex patterns.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from reasonix.tool.base import Tool


class GrepTool(Tool):
    """Search for a regular expression in files."""

    @property
    def name(self) -> str:
        return "grep"

    @property
    def description(self) -> str:
        return (
            "Search for a regular expression in a file or recursively under a directory. "
            "Skips hidden files and files matched by .gitignore patterns. "
            "Returns matching lines as path:line:text, capped at 200 matches."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regular expression (RE2 syntax)"},
                "path": {
                    "type": "string",
                    "description": "File or directory to search (default: current directory)",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Abort after this many seconds (default 30, max 300)",
                    "default": 30,
                },
            },
            "required": ["pattern"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        pattern = args["pattern"]
        path = args.get("path", ".")
        timeout = min(args.get("timeout_seconds", 30), 300)

        try:
            compiled = re.compile(pattern)
        except re.error as e:
            return f"Invalid regex: {e}"

        root = Path(path)
        if not root.exists():
            return f"Path not found: {path}"

        results: list[str] = []
        try:
            if root.is_file():
                self._search_file(compiled, root, results)
            else:
                self._search_dir(compiled, root, results, timeout)
        except _SearchTimeoutError:
            results.append("(search timed out)")

        if not results:
            return f"No matches for pattern: {pattern}"
        return "\n".join(results[:200])

    def _search_file(
        self, compiled: re.Pattern[str], path: Path, results: list[str]
    ) -> None:
        """Search a single file."""
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f, 1):
                    if compiled.search(line):
                        relative = str(path).replace("\\", "/")
                        results.append(f"{relative}:{i}:{line.rstrip()}")
                        if len(results) >= 200:
                            return
        except (PermissionError, IsADirectoryError):
            pass

    def _search_dir(
        self, compiled: re.Pattern[str], root: Path, results: list[str], timeout: int
    ) -> None:
        """Recursively search a directory."""
        import time
        start = time.time()
        for entry in root.rglob("*"):
            if time.time() - start > timeout:
                raise _SearchTimeoutError()
            if entry.is_file() and not entry.name.startswith("."):
                self._search_file(compiled, entry, results)
                if len(results) >= 200:
                    return


class _SearchTimeoutError(Exception):
    pass
