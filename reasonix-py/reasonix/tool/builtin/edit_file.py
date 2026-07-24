"""Built-in tool: edit_file — replace exact string in a file."""

import json
from pathlib import Path
from typing import Any

from reasonix.diff import Change, build_change
from reasonix.tool.base import Tool


class EditFileTool(Tool):
    """Replace an exact string in a file with another string."""

    @property
    def name(self) -> str:
        return "edit_file"

    @property
    def description(self) -> str:
        return (
            "Replace an exact string in a file with another. "
            "old_string must occur exactly once; add surrounding context to disambiguate."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {
                    "type": "string",
                    "description": "Exact text to replace (must occur once)",
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text (may be empty to delete)",
                },
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        path = Path(args["path"])
        old = args["old_string"]
        new = args["new_string"]

        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except IsADirectoryError:
            return f"Error: is a directory: {path}"
        except PermissionError:
            return f"Error: permission denied: {path}"
        except UnicodeDecodeError:
            return f"Error: file is not valid UTF-8: {path}"
        except OSError as e:
            return f"Error reading {path}: {e}"

        count = content.count(old)
        if count == 0:
            return f"Error: old_string not found in {path}"
        if count > 1:
            return (
                f"Error: old_string occurs {count} times (must occur exactly once). "
                "Add surrounding context."
            )

        new_content = content.replace(old, new, 1)
        path.write_text(new_content, encoding="utf-8")
        return f"Edited {path}: replaced {len(old)} chars with {len(new)} chars"

    async def preview(self, args_json: str) -> Change | None:
        args = json.loads(args_json)
        path = Path(args["path"]).resolve()
        if not path.is_file():
            return None
        content = path.read_text(encoding="utf-8")
        old = str(args["old_string"])
        if content.count(old) != 1:
            return None
        new_content = content.replace(old, str(args["new_string"]), 1)
        return build_change(str(path), content, new_content, "Edit file")
