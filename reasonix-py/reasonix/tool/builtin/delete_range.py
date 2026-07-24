"""Built-in tool: delete_range — delete a contiguous text range from a file."""

import json
from pathlib import Path
from typing import Any

from reasonix.diff import Change, build_change
from reasonix.tool.base import Tool


class DeleteRangeTool(Tool):
    """Delete a contiguous text range from a file using exact start/end anchors."""

    @property
    def name(self) -> str:
        return "delete_range"

    @property
    def description(self) -> str:
        return (
            "Delete a contiguous text range from a file using exact start/end text anchors. "
            "Each anchor must match exactly one line."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "start_anchor": {
                    "type": "string",
                    "description": "Exact text of the first line to delete (must be unique)",
                },
                "end_anchor": {
                    "type": "string",
                    "description": "Exact text of the last line to delete (must be unique)",
                },
                "inclusive": {
                    "type": "boolean",
                    "description": "Whether to include the anchor lines (default true)",
                },
            },
            "required": ["path", "start_anchor", "end_anchor"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        path = Path(args["path"])
        start_anchor = args["start_anchor"]
        end_anchor = args["end_anchor"]
        inclusive = args.get("inclusive", True)

        if not path.is_file():
            return f"Error: file not found: {path}"

        try:
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        except Exception as e:
            return f"Error reading {path}: {e}"

        # Find anchor lines
        start_indices = [i for i, line in enumerate(lines) if start_anchor in line]
        end_indices = [i for i, line in enumerate(lines) if end_anchor in line]

        if len(start_indices) != 1:
            return f"Error: start_anchor occurs {len(start_indices)} times (must be unique)"
        if len(end_indices) != 1:
            return f"Error: end_anchor occurs {len(end_indices)} times (must be unique)"

        start_idx = start_indices[0]
        end_idx = end_indices[0]

        if start_idx > end_idx:
            return "Error: start_anchor found after end_anchor"

        if inclusive:
            del lines[start_idx:end_idx + 1]
        else:
            del lines[start_idx + 1:end_idx]

        path.write_text("".join(lines), encoding="utf-8")
        return f"Deleted range {start_idx}-{end_idx} from {path}"

    async def preview(self, args_json: str) -> Change | None:
        args = json.loads(args_json)
        path = Path(args["path"]).resolve()
        if not path.is_file():
            return None
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        start_indices = [
            index for index, line in enumerate(lines)
            if str(args["start_anchor"]) in line
        ]
        end_indices = [
            index for index, line in enumerate(lines)
            if str(args["end_anchor"]) in line
        ]
        if len(start_indices) != 1 or len(end_indices) != 1:
            return None
        start_idx, end_idx = start_indices[0], end_indices[0]
        if start_idx > end_idx:
            return None
        if bool(args.get("inclusive", True)):
            del lines[start_idx:end_idx + 1]
        else:
            del lines[start_idx + 1:end_idx]
        return build_change(str(path), content, "".join(lines), "Delete range")
