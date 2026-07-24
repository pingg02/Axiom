"""Built-in tool: todo_write — record and update a structured task list."""

import json
from typing import Any

from reasonix.tool.base import Tool


class TodoWriteTool(Tool):
    """Record and update a structured task list for the current work."""

    @property
    def name(self) -> str:
        return "todo_write"

    @property
    def description(self) -> str:
        return (
            "Record and update a structured task list for the current work. "
            "Send the COMPLETE list every call — it replaces the previous one."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                            "activeForm": {"type": "string"},
                            "level": {"type": "integer"},
                        },
                        "required": ["content", "status"],
                    },
                },
            },
            "required": ["todos"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        todos = args.get("todos", [])
        total = len(todos)
        done = sum(1 for t in todos if t.get("status") == "completed")
        return f"Todos updated: {total} total, {done} completed"
