"""
TUI — Claude Code 风格的终端交互界面。

使用 Rich 实现：彩色输出、Markdown 渲染、工具调用卡片、Reasoning 面板。
"""

from __future__ import annotations

import asyncio

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.rule import Rule
from rich.table import Table

from reasonix.boot import build_controller_async
from reasonix.event import Event, Kind, Sink

console = Console()


class _TuiSink(Sink):
    """Rich 终端 sink — 实时渲染事件流。"""

    def __init__(self) -> None:
        self._current_text = ""

    def emit(self, event: Event) -> None:
        if event.kind == Kind.TEXT:
            if event.text:
                self._current_text += event.text
                console.print(event.text, end="", style="white")

        elif event.kind == Kind.REASONING:
            if event.reasoning:
                console.print(f"[dim]{event.reasoning}[/]", end="")

        elif event.kind == Kind.MESSAGE:
            if self._current_text:
                console.print()  # newline after streaming

        elif event.kind == Kind.TOOL_DISPATCH:
            tool_name = event.tool.name if event.tool else "tool"
            icon = "🔍" if event.tool and event.tool.read_only else "🔧"
            console.print(f"  {icon} {tool_name}", style="yellow")

        elif event.kind == Kind.TOOL_RESULT:
            if event.tool and event.tool.error:
                console.print(f"  ⚠️ {event.tool.error}", style="red")

        elif event.kind == Kind.ERROR:
            console.print(f"\n[red]Error: {event.error}[/]")

        elif event.kind == Kind.NOTICE:
            if event.level == "warning":
                console.print(f"\n[yellow]⚠ {event.text}[/]")

        elif event.kind == Kind.TURN_DONE:
            self._current_text = ""


async def run_tui() -> int:
    """Run interactive TUI."""
    sink = _TuiSink()
    controller = await build_controller_async(sink=sink)

    # Header
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Reasonix[/] — AI Coding Agent",
        subtitle="Type /help for commands, /quit to exit",
        border_style="cyan",
    ))
    console.print()

    try:
        while True:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: Prompt.ask("[bold cyan]>>>[/]")
                )
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Goodbye![/]")
                break

            if not line or not line.strip():
                continue

            if line.strip() == "/quit":
                break
            elif line.strip() == "/help":
                _show_help()
                continue
            elif line.strip().startswith("/model "):
                console.print("  [dim]Model switching not yet implemented[/]")
                continue

            console.print(Rule(style="dim"))
            await controller.send(line)
            await controller.wait_for_turn()
            console.print(Rule(style="dim"))

    finally:
        await controller.close()

    return 0


def _show_help() -> None:
    table = Table(show_header=False, box=None)
    table.add_column("Command", style="cyan")
    table.add_column("Description")
    table.add_row("/quit", "Exit Reasonix")
    table.add_row("/help", "Show this help")
    table.add_row("/model <name>", "Switch model")
    table.add_row("", "")
    table.add_row("[dim]Or just type anything to chat![/]", "")
    console.print(Panel(table, title="Help", border_style="blue"))
