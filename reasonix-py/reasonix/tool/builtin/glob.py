"""Built-in tool: glob — find files matching a glob pattern."""

import json
from pathlib import Path
from typing import Any

from reasonix.tool.base import Tool


class GlobTool(Tool):
    """Find files matching a glob pattern."""

    @property
    def name(self) -> str:
        return "glob"

    @property
    def description(self) -> str:
        return (
            "Find files matching a glob pattern (e.g. '*.go', '**/*.test.ts'). "
            "Supports * ? and ** recursive patterns. Returns only files, not directories."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern to match"},
            },
            "required": ["pattern"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        pattern = args["pattern"]
        root = Path.cwd()
        results = sorted(str(p.relative_to(root)) for p in root.glob(pattern) if p.is_file())
        if not results:
            return f"No files match: {pattern}"
        return "\n".join(results[:200])
