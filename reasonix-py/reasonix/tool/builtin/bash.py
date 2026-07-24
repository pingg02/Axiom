"""
Built-in tool: bash — execute shell commands.

Wraps asyncio.create_subprocess_shell for safe command execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
from collections.abc import Callable
from typing import Any, cast

from reasonix.tool.base import Tool


class BashTool(Tool):
    """Execute shell commands and return stdout+stderr."""

    @property
    def name(self) -> str:
        return "bash"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command and return combined stdout/stderr. "
            "Use for builds, tests, git, package managers, and running scripts."
        )

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Maximum execution time in seconds (default 30)",
                    "default": 30,
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory (default: project root)",
                },
            },
            "required": ["command"],
        }

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        command = args["command"]
        timeout = args.get("timeout_seconds", 30)
        workdir = args.get("workdir", None)

        try:
            process_kwargs: dict[str, Any] = {}
            if os.name == "nt":
                process_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                process_kwargs["preexec_fn"] = cast(
                    Callable[[], int], getattr(os, "setsid")
                )

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
                **process_kwargs,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
            output = ""
            if stdout:
                output += stdout.decode("utf-8", errors="replace")
            if stderr:
                if output:
                    output += "\n"
                output += stderr.decode("utf-8", errors="replace")

            if process.returncode != 0:
                output += f"\n(exit code: {process.returncode})"

            return output[:64 * 1024]  # cap at 64KB

        except TimeoutError:
            await _kill_process_tree(process)
            return f"Command timed out after {timeout}s"
        except FileNotFoundError as e:
            return f"Command not found: {e}"
        except Exception as e:
            return f"Error executing command: {e}"


async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    """Terminate a timed-out shell and any child process it spawned."""
    if process.returncode is not None:
        return

    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill",
            "/PID",
            str(process.pid),
            "/T",
            "/F",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await killer.communicate()
    else:
        killpg = cast(Callable[[int, int], None], getattr(os, "killpg"))
        sigkill = cast(int, getattr(signal, "SIGKILL"))
        with contextlib.suppress(ProcessLookupError):
            killpg(process.pid, sigkill)

    with contextlib.suppress(ProcessLookupError):
        process.kill()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=5)
