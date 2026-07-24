"""Built-in tool: read_file - read text files with line offsets."""

from __future__ import annotations

import json
from typing import Any

from reasonix.tool.base import Tool


class ReadFileTool(Tool):
    """Read a text file with optional line offset/limit."""

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read a text file and return its contents. "
            "Output prefixes each line with its 0-based line number."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {
                    "type": "integer",
                    "description": "0-based line offset to start reading from",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum lines to return (default 2000)",
                },
            },
            "required": ["path"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        path = args["path"]
        offset = args.get("offset", 0)
        limit = args.get("limit", 2000)

        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: is a directory: {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

        total = len(lines)
        if offset < 0:
            offset = max(0, total + offset)
        if offset > total:
            return f"Error: offset {offset} exceeds file length {total}"

        selected = lines[offset:offset + limit]
        result = "\n".join(
            f"{offset + i:>7} | {line.rstrip()}"
            for i, line in enumerate(selected)
        )
        trailer = []
        if offset > 0:
            trailer.append(
                f"(showing lines {offset + 1}-{min(offset + limit, total)} of {total})"
            )
        else:
            trailer.append(f"(showing {min(limit, total)} of {total} lines)")
        if offset + limit < total:
            trailer.append(f"(use offset={offset + limit} to continue)")
        if result:
            result += "\n" + "\n".join(trailer)
        else:
            result = "\n".join(trailer)
        return result
