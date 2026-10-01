"""Built-in tool: task — run a focused sub-task in an isolated sub-agent."""

from typing import Any

from reasonix.tool.base import Tool


class TaskTool(Tool):
    """Spawn a sub-agent for a focused sub-task."""

    @property
    def name(self) -> str:
        return "task"

    @property
    def description(self) -> str:
        return (
            "Spawn a sub-agent for a focused sub-task. "
            "The sub-agent runs in its own session and returns a final answer."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task prompt for the sub-agent"},
                "description": {"type": "string", "description": "Short label for the sub-task"},
                "subagent_model": {"type": "string", "description": "Optional model override"},
            },
            "required": ["prompt"],
        }

    async def execute(self, args_json: str) -> str:
        return "Error: task needs a Controller-managed runner; no sub-agent was started."
