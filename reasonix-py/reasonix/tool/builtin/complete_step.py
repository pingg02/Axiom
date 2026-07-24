"""Built-in tool: complete_step — sign off a completed plan step with evidence."""

import json
from typing import Any

from reasonix.tool.base import Tool


class CompleteStepTool(Tool):
    """Sign off a completed plan step with evidence."""

    @property
    def name(self) -> str:
        return "complete_step"

    @property
    def description(self) -> str:
        return (
            "Record the evidence-backed completion of ONE step of an approved plan. "
            "Call it as you finish each step instead of silently moving on."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "Step title or number"},
                "result": {"type": "string", "description": "What is now true or changed"},
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "kind": {
                                "type": "string",
                                "enum": ["verification", "diff", "files", "manual"],
                            },
                            "summary": {"type": "string"},
                            "command": {"type": "string"},
                        },
                        "required": ["kind", "summary"],
                    },
                },
            },
            "required": ["result", "evidence"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        step = args.get("step", "(unnamed)")
        result = args.get("result", "")
        evidence_count = len(args.get("evidence", []))
        return (
            f"Step '{step}' signed off with {evidence_count} evidence item(s). "
            f"Result: {result[:200]}"
        )
