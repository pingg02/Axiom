"""Built-in tool: notebook_edit — edit a Jupyter notebook cell."""

import json
from pathlib import Path
from typing import Any

from reasonix.tool.base import Tool


class NotebookEditTool(Tool):
    """Edit one cell of a Jupyter notebook (.ipynb)."""

    @property
    def name(self) -> str:
        return "notebook_edit"

    @property
    def description(self) -> str:
        return (
            "Edit one cell of a Jupyter notebook (.ipynb). "
            "Supports replace, insert, and delete operations on cells."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the .ipynb notebook"},
                "cell_number": {
                    "type": "integer",
                    "description": "0-based index of the target cell",
                },
                "edit_mode": {
                    "type": "string",
                    "enum": ["replace", "insert", "delete"],
                    "description": "replace (default), insert, or delete",
                },
                "cell_type": {
                    "type": "string",
                    "enum": ["code", "markdown"],
                    "description": "Cell type for insert (required for insert)",
                },
                "new_source": {
                    "type": "string",
                    "description": "The cell's new source text (replace/insert)",
                },
            },
            "required": ["path", "cell_number"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        path = Path(args["path"])
        cell_number = args["cell_number"]
        edit_mode = args.get("edit_mode", "replace")
        cell_type = args.get("cell_type", "code")
        new_source = args.get("new_source", "")

        if not path.is_file():
            return f"Error: file not found: {path}"

        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"Error: invalid JSON in {path}"

        cells = content.get("cells", [])
        if edit_mode == "delete":
            if 0 <= cell_number < len(cells):
                cells.pop(cell_number)
                content["cells"] = cells
                path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
                return f"Deleted cell {cell_number} from {path}"
            return f"Error: cell_number {cell_number} out of range (0-{len(cells) - 1})"

        elif edit_mode == "insert":
            new_cell = {
                "cell_type": cell_type,
                "source": [new_source],
                "metadata": {},
                "outputs": [] if cell_type == "code" else None,
            }
            insert_pos = max(0, min(cell_number + 1, len(cells)))
            cells.insert(insert_pos, new_cell)
            content["cells"] = cells
            path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
            return f"Inserted {cell_type} cell at position {insert_pos} in {path}"

        else:  # replace
            if 0 <= cell_number < len(cells):
                cells[cell_number]["source"] = [new_source]
                if "cell_type" in args:
                    cells[cell_number]["cell_type"] = cell_type
                content["cells"] = cells
                path.write_text(json.dumps(content, ensure_ascii=False, indent=1), encoding="utf-8")
                return f"Replaced cell {cell_number} in {path}"
            return f"Error: cell_number {cell_number} out of range (0-{len(cells) - 1})"
