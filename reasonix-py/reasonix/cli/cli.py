"""
CLI entry point — subcommand routing and flag parsing.

Usage:
  reasonix chat         Start interactive TUI session
  reasonix run <msg>    Run a single prompt and exit
  reasonix serve        Start HTTP/SSE server
  reasonix --version    Print version
  reasonix --help       Print help
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys

from reasonix.boot import ConfigError
from reasonix.boot import build_controller_async as build_controller
from reasonix.event import Event, Kind, Sink

VERSION = "0.2.1"


class _PrintSink(Sink):
    """Simple sink that prints events to stderr (for run mode)."""

    def emit(self, event: Event) -> None:
        if event.kind == Kind.TEXT:
            print(event.text, end="", flush=True)
        elif event.kind == Kind.MESSAGE:
            if event.text:
                print(event.text)
        elif event.kind == Kind.REASONING:
            pass  # hide reasoning in run mode
        elif event.kind == Kind.ERROR:
            print(f"\nError: {event.error}", file=sys.stderr)
        elif event.kind == Kind.NOTICE:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reasonix",
        description="AI coding agent — config- and plugin-driven.",
    )
    parser.add_argument(
        "--version", action="store_true", help="Print version and exit"
    )

    sub = parser.add_subparsers(dest="command", help="Subcommand")

    # chat
    sub.add_parser("chat", help="Start interactive TUI session")

    # run
    run_parser = sub.add_parser("run", help="Run a single prompt and exit")
    run_parser.add_argument("prompt", nargs="*", help="Prompt text")

    # Quick prompt: reasonix "write a file" (no subcommand)
    parser.add_argument("direct_prompt", nargs="*",
                        help="Prompt text (when no subcommand is given)")

    # serve
    sub.add_parser("serve", help="Start HTTP/SSE server")
    # desktop
    desktop_parser = sub.add_parser("desktop", help="Start WebSocket desktop bridge")
    desktop_parser.add_argument("--host", default="127.0.0.1")
    desktop_parser.add_argument("--port", type=int, default=9092)

    return parser


async def _run_mode(prompt: str) -> int:
    """Single-prompt execution."""
    sink = _PrintSink()
    controller = await build_controller(sink=sink)
    await controller.send(prompt)
    await controller.wait_for_turn()
    await controller.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(f"Axiom {VERSION} (Reasonix engine, Python {platform.python_version()})")
        return 0

    try:
        # Quick prompt: reasonix "write a file"
        if args.direct_prompt and not args.command:
            prompt = " ".join(args.direct_prompt)
            asyncio.run(_run_mode(prompt))
            return 0

        if not args.command or args.command == "chat":
            from reasonix.cli.chat_tui import run_tui
            return asyncio.run(run_tui())

        elif args.command == "run":
            prompt = " ".join(args.prompt)
            if not prompt:
                print("Error: run requires a prompt", file=sys.stderr)
                return 1
            return asyncio.run(_run_mode(prompt))

        elif args.command == "serve":
            from reasonix.serve.server import run_server
            return asyncio.run(run_server())

        elif args.command == "desktop":
            from reasonix.desktop import run_server as run_desktop
            asyncio.run(run_desktop(args.host, args.port))
            return 0
    except ConfigError as exc:
        print(f"Reasonix configuration error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Reasonix failed to start: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
