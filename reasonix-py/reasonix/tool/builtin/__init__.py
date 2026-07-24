"""
Built-in tool catalog — all built-in tool classes registered here.

Importing this module triggers side-effect registration via BUILTIN_TOOL_CLASSES.
"""

from __future__ import annotations

from reasonix.tool.base import Tool
from reasonix.tool.builtin.ask import AskTool
from reasonix.tool.builtin.bash import BashTool
from reasonix.tool.builtin.complete_step import CompleteStepTool
from reasonix.tool.builtin.delete_range import DeleteRangeTool
from reasonix.tool.builtin.edit_file import EditFileTool
from reasonix.tool.builtin.forget import ForgetTool
from reasonix.tool.builtin.glob import GlobTool
from reasonix.tool.builtin.grep import GrepTool
from reasonix.tool.builtin.move_file import MoveFileTool
from reasonix.tool.builtin.notebook_edit import NotebookEditTool
from reasonix.tool.builtin.readfile import ReadFileTool
from reasonix.tool.builtin.remember import RememberTool
from reasonix.tool.builtin.task import TaskTool
from reasonix.tool.builtin.todo_write import TodoWriteTool
from reasonix.tool.builtin.web_fetch import WebFetchTool
from reasonix.tool.builtin.writefile import WriteFileTool

# All built-in tool classes — boot iterates these to populate the registry
BUILTIN_TOOL_CLASSES: list[type[Tool]] = [
    AskTool,
    BashTool,
    CompleteStepTool,
    DeleteRangeTool,
    EditFileTool,
    ForgetTool,
    GlobTool,
    GrepTool,
    MoveFileTool,
    NotebookEditTool,
    ReadFileTool,
    RememberTool,
    TaskTool,
    TodoWriteTool,
    WebFetchTool,
    WriteFileTool,
]
