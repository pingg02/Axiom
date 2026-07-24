"""Built-in tool: ask — ask the user multiple-choice questions."""

import json
from typing import Any

from reasonix.tool.base import Tool


class AskTool(Tool):
    """Ask the user one or more multiple-choice questions."""

    @property
    def name(self) -> str:
        return "ask"

    @property
    def description(self) -> str:
        return (
            "Ask the user one or more multiple-choice questions when you hit "
            "a decision that is genuinely theirs to make."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "header": {"type": "string"},
                            "question": {"type": "string"},
                            "options": {
                                "type": "array",
                                "items": {"type": "object", "properties": {
                                    "label": {"type": "string"},
                                    "description": {"type": "string"},
                                }, "required": ["label"]},
                            },
                            "multi_select": {"type": "boolean"},
                        },
                        "required": ["question", "options"],
                    },
                },
            },
            "required": ["questions"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, args_json: str) -> str:
        # Placeholder — real ask requires interactive frontend callback
        args = json.loads(args_json)
        qs = args.get("questions", [])
        return json.dumps(
            {"status": "deferred", "count": len(qs),
             "message": "Interactive ask requires frontend callback integration"},
            ensure_ascii=False,
        )
