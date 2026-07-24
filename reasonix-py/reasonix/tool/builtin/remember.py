"""Built-in tool: remember — save a durable fact to project memory."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from reasonix.tool.base import Tool


class RememberTool(Tool):
    """Save a durable fact so it survives across sessions."""

    @property
    def name(self) -> str:
        return "remember"

    @property
    def description(self) -> str:
        return (
            "Save a durable fact to project memory so it survives across sessions. "
            "Use for things worth remembering long-term: user preferences, guidance, "
            "project constraints, or external resource references."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short kebab-case slug, e.g. 'prefers-tabs'",
                },
                "description": {
                    "type": "string",
                    "description": "One-line hook shown in memory index",
                },
                "body": {
                    "type": "string",
                    "description": "The fact itself (Markdown)",
                },
                "type": {
                    "type": "string",
                    "enum": ["user", "feedback", "project", "reference"],
                    "description": "Category of the fact",
                },
                "title": {
                    "type": "string",
                    "description": "Short human-readable label",
                },
            },
            "required": ["name", "description", "body"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        name = args["name"]
        description = args["description"]
        body = args["body"]
        fact_type = args.get("type", "project")
        title = args.get("title", name)

        # Find project memory directory
        cwd = Path.cwd()
        memory_dir = cwd / ".reasonix" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        # Write frontmatter Markdown
        frontmatter = {
            "title": title,
            "description": description,
            "type": fact_type,
            "created": datetime.now().isoformat(),
        }
        content_parts = [
            "---",
            "\n".join(f"{k}: {v}" for k, v in frontmatter.items()),
            "---",
            "",
            body,
        ]
        path = memory_dir / f"{name}.md"
        path.write_text("\n".join(content_parts), encoding="utf-8")

        return f"Saved memory '{name}' to {path} ({len(body)} bytes)"
