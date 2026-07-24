"""Built-in tool: move_file — move or rename a file."""

import json
from pathlib import Path
from typing import Any

from reasonix.tool.base import Tool


class MoveFileTool(Tool):
    """Move or rename a file, creating parent directories as needed."""

    @property
    def name(self) -> str:
        return "move_file"

    @property
    def description(self) -> str:
        return (
            "Move or rename a file from source_path to destination_path. "
            "Creates the destination parent directory as needed."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "source_path": {
                    "type": "string",
                    "description": "Existing file path to move",
                },
                "destination_path": {
                    "type": "string",
                    "description": "Destination file path; must not already exist",
                },
            },
            "required": ["source_path", "destination_path"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        src = Path(args["source_path"])
        dst = Path(args["destination_path"])

        if not src.exists():
            return f"Error: source not found: {src}"
        if dst.exists():
            return f"Error: destination already exists: {dst}"

        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        return f"Moved {src} to {dst}"
