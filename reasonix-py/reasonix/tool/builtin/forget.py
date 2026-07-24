"""Built-in tool: forget — delete a saved memory fact."""

import json
from pathlib import Path
from typing import Any

from reasonix.tool.base import Tool


class ForgetTool(Tool):
    """Delete a saved memory by name."""

    @property
    def name(self) -> str:
        return "forget"

    @property
    def description(self) -> str:
        return (
            "Delete a saved memory by name when it is wrong, stale, or superseded, "
            "so it stops loading into future sessions."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Slug of the memory to delete, e.g. 'prefers-tabs'",
                },
            },
            "required": ["name"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        name = args["name"]

        # Check project memory
        path = Path.cwd() / ".reasonix" / "memory" / f"{name}.md"
        if path.is_file():
            path.unlink()
            return f"Deleted memory '{name}' from {path}"
        return f"Memory '{name}' not found"
