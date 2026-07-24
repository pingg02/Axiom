"""
Built-in tool: write_file — write content to a file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from reasonix.diff import Change, build_change
from reasonix.tool.base import Tool


class WriteFileTool(Tool):
    """Write content to a file, creating parent directories as needed."""

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write content to a file at the given path (overwriting existing content). "
            "Creates parent directories as needed."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        path = Path(args["path"])
        content = args["content"]

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        except IsADirectoryError:
            return f"Error: is a directory: {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    async def preview(self, args_json: str) -> Change:
        """Preview the write as a diff."""
        args = json.loads(args_json)
        path = Path(args["path"]).resolve()
        old_content = path.read_text(encoding="utf-8") if path.is_file() else None
        return build_change(
            str(path),
            old_content,
            str(args["content"]),
            "Write file",
        )
