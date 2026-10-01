"""WebSocket bridge between the Axiom desktop renderer and agent controller."""

from __future__ import annotations

import asyncio
import ctypes
import hmac
import json
import logging
import os
import uuid
from collections import deque
from dataclasses import asdict
from pathlib import Path
from typing import Any

from reasonix.boot import (
    ConfigError,
    build_controller_async,
    build_unconfigured_controller,
)
from reasonix.diff import build_change
from reasonix.event import Event, Kind, Sink, event_to_frontend_dict
from reasonix.history import SessionStore, default_history_path

logger = logging.getLogger(__name__)

_WORKSPACE_SEARCH_IGNORES = {
    ".build-cache",
    ".codegraph",
    ".git",
    ".idea",
    ".mvn",
    ".playwright-cli",
    ".pytest_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "axiom-build",
    "build",
    "dist",
    "node_modules",
    "output",
    "release",
    "reasonix-build",
    "reasonix-build-latest",
    "target",
    "venv",
}
_WORKSPACE_SEARCH_SCAN_LIMIT = 25_000
_WORKSPACE_SEARCH_RESULT_LIMIT = 40


def _search_workspace_entries(workspace: Path, raw_query: str) -> list[dict[str, object]]:
    """Return bounded, workspace-relative file suggestions for the composer."""
    root = workspace.resolve()
    query = raw_query.strip().replace("\\", "/").removeprefix("./").casefold()[:200]
    if not root.is_dir():
        return []

    if not query:
        try:
            entries = sorted(
                (
                    child
                    for child in root.iterdir()
                    if child.name not in _WORKSPACE_SEARCH_IGNORES
                    and not child.name.startswith(".")
                ),
                key=lambda item: (not item.is_dir(), item.name.casefold()),
            )
        except OSError:
            return []
        return [
            {
                "path": child.relative_to(root).as_posix(),
                "name": child.name,
                "is_dir": child.is_dir(),
            }
            for child in entries[:_WORKSPACE_SEARCH_RESULT_LIMIT]
        ]

    matches: list[tuple[tuple[int, int, int, str], Path]] = []
    scanned = 0
    for current, directories, files in os.walk(root):
        directories[:] = [
            name
            for name in directories
            if name not in _WORKSPACE_SEARCH_IGNORES and not name.startswith(".")
        ]
        current_path = Path(current)
        for name, is_dir in [(directory, True) for directory in directories] + [
            (file_name, False) for file_name in files
        ]:
            scanned += 1
            if scanned > _WORKSPACE_SEARCH_SCAN_LIMIT:
                break
            candidate = current_path / name
            try:
                relative = candidate.relative_to(root).as_posix()
            except ValueError:
                continue
            relative_folded = relative.casefold()
            name_folded = name.casefold()
            if name_folded == query:
                rank = 0
            elif name_folded.startswith(query):
                rank = 1
            elif relative_folded.startswith(query):
                rank = 2
            elif query in name_folded:
                rank = 3
            elif query in relative_folded:
                rank = 4
            else:
                continue
            matches.append(
                (
                    (rank, relative.count("/"), 0 if is_dir else 1, relative_folded),
                    candidate,
                )
            )
        if scanned > _WORKSPACE_SEARCH_SCAN_LIMIT:
            break

    matches.sort(key=lambda item: item[0])
    return [
        {
            "path": candidate.relative_to(root).as_posix(),
            "name": candidate.name,
            "is_dir": candidate.is_dir(),
        }
        for _, candidate in matches[:_WORKSPACE_SEARCH_RESULT_LIMIT]
    ]


def _process_is_alive(pid: int) -> bool:
    """Check a parent PID without adding a runtime dependency."""
    if pid <= 0:
        return False
    if os.name == "nt":
        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        try:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            still_active = 259
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


async def _watch_parent(parent_pid: int, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        await asyncio.sleep(2)
        if not _process_is_alive(parent_pid):
            logger.info("Axiom parent process %s exited; stopping desktop bridge", parent_pid)
            stopped.set()
            return


class WebSocketSink(Sink):
    """Serialize controller events onto an asynchronous send queue."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8192)

    def emit(self, event: Event) -> None:
        self.queue.put_nowait(json.dumps(event_to_frontend_dict(event), ensure_ascii=False))


class BridgeClient:
    """One desktop WebSocket connection and its isolated agent session.

    The agent controller is built lazily, only after the connection proves
    it holds the per-launch security token (when one is configured). Probe
    connections from the Electron readiness check therefore never pay the
    provider/MCP startup cost, and unauthenticated local processes cannot
    drive the agent.
    """

    def __init__(
        self,
        websocket: Any,
        required_token: str = "",
        runtime: DesktopRuntime | None = None,
    ) -> None:
        self.ws = websocket
        self.sink = WebSocketSink()
        self.controller: Any | None = None
        self._required_token = required_token or ""
        self._authenticated = not self._required_token
        self._send_task: asyncio.Task[None] | None = None
        self._send_lock = asyncio.Lock()
        self._workflow_task: asyncio.Task[None] | None = None
        self._workflow_run: dict[str, Any] | None = None
        self._local_controller: Any | None = None
        self.remote: dict[str, Any] | None = None
        self._runtime = runtime
        self._experiment_store: Any | None = None

    @classmethod
    async def create(
        cls,
        websocket: Any,
        required_token: str = "",
        runtime: DesktopRuntime | None = None,
    ) -> BridgeClient:
        return cls(websocket, required_token, runtime)

    def _authenticate(self, supplied: str) -> bool:
        if not self._required_token:
            return True
        if not hmac.compare_digest(supplied or "", self._required_token):
            return False
        self._authenticated = True
        return True

    async def _ensure_controller(self) -> None:
        if self.controller is not None:
            return
        history_store = SessionStore(default_history_path())
        try:
            self.controller = await build_controller_async(
                sink=self.sink,
                history_store=history_store,
            )
        except ConfigError as exc:
            logger.info("Desktop provider setup required: %s", exc)
            self.controller = build_unconfigured_controller(
                str(exc),
                sink=self.sink,
                history_store=history_store,
            )

    async def start(self) -> None:
        self._send_task = asyncio.create_task(self._send_loop())

    async def handle_message(self, raw: str) -> None:
        try:
            message = json.loads(raw)
            if not isinstance(message, dict):
                raise ValueError("Message must be a JSON object")
            action = str(message.get("action", ""))
            if action == "auth":
                if not self._authenticate(str(message.get("token", ""))):
                    await self._send_json({"kind": "error", "error": "invalid security token"})
                    return
                if self._runtime:
                    await self._runtime.attach(self)
                    return
                await self._ensure_controller()
                await self.send_status()
                return
            if not self._authenticated:
                await self._send_json({"kind": "error", "error": "authentication required"})
                return
            if self._runtime:
                if self not in self._runtime.clients:
                    await self._runtime.attach(self)
                await self._runtime.handle_message(raw)
                return
            await self._ensure_controller()
            if action == "send":
                text = str(message.get("text", "")).strip()
                if text:
                    await self.controller.send(text)
            elif action == "cancel":
                await self.controller.cancel()
            elif action == "approve":
                await self.controller.approve(
                    str(message.get("request_id", "")),
                    bool(message.get("allow", False)),
                    str(message.get("scope", "once")),
                )
            elif action == "approve_all":
                future_mode = str(message.get("future_mode", "")).strip()
                if future_mode:
                    await self._set_permission_mode(future_mode)
                await self.controller.approve_all(
                    bool(message.get("allow", False)),
                    str(message.get("scope", "once")),
                )
            elif action == "set_permission_mode":
                await self._set_permission_mode(str(message.get("mode", "")))
            elif action == "connect_remote":
                await self._connect_remote(message)
            elif action == "disconnect_remote":
                await self._disconnect_remote()
            elif action in {"submit_experiment", "refresh_experiment", "stop_experiment"}:
                await self._experiment_action(action, message)
            elif action == "answer_ask":
                answers = message.get("answers", [])
                if not isinstance(answers, list):
                    raise ValueError("answers must be an array")
                await self.controller.answer_ask(
                    str(message.get("ask_id", "")),
                    [str(answer) for answer in answers],
                )
            elif action == "new_session":
                await self.controller.new_session()
            elif action == "resume_session":
                await self.controller.resume_session(str(message.get("session_id", "")))
            elif action == "delete_session":
                await self.controller.delete_session(str(message.get("session_id", "")))
            elif action == "undo_last_turn":
                restored = await self.controller.undo_last_turn()
                self.sink.emit(
                    Event(
                        kind=Kind.NOTICE,
                        text=(
                            f"已撤销最近一轮的 {restored} 项文件变更。"
                            if restored
                            else "当前会话没有可撤销的文件变更。"
                        ),
                    )
                )
            elif action == "save_workflow":
                name = str(message.get("name", "")).strip()
                raw_steps = message.get("steps", [])
                if not isinstance(raw_steps, list):
                    raise ValueError("Workflow steps must be an array")
                steps = [str(step).strip() for step in raw_steps if str(step).strip()]
                if not name:
                    raise ValueError("Workflow name is required")
                if not steps:
                    raise ValueError("Workflow needs at least one step")
                if len(steps) > 20:
                    raise ValueError("Workflow cannot contain more than 20 steps")
                workflow_id = str(message.get("workflow_id", "")).strip() or str(uuid.uuid4())
                self.controller.save_workflow(workflow_id, name, steps)
            elif action == "delete_workflow":
                workflow_id = str(message.get("workflow_id", "")).strip()
                if self._workflow_is_running(workflow_id):
                    raise ValueError("Cannot delete a running workflow")
                self.controller.delete_workflow(workflow_id)
            elif action == "run_workflow":
                self._start_workflow(str(message.get("workflow_id", "")).strip())
            elif action == "cancel_workflow":
                await self._cancel_workflow()
            elif action == "search_workspace":
                query = str(message.get("query", ""))
                if self.remote:
                    paths = await self.controller.client.request(
                        "GET",
                        "/find/file",
                        params={"query": query[:200], "limit": "40"},
                    )
                    items = [
                        {
                            "path": path,
                            "name": str(path).rstrip("/").rsplit("/", 1)[-1],
                            "is_dir": str(path).endswith("/"),
                        }
                        for path in paths
                    ]
                else:
                    items = await asyncio.to_thread(
                        _search_workspace_entries,
                        Path.cwd(),
                        query,
                    )
                await self._send_json(
                    {
                        "kind": "workspace_suggestions",
                        "query": query[:200],
                        "workspace_suggestions": items,
                    }
                )
                return
            elif action != "status":
                raise ValueError(f"Unknown action: {action or '<empty>'}")
            await self.send_status()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            await self._send_json({"kind": "error", "error": str(exc)})
        except Exception as exc:
            logger.exception("Desktop bridge action failed")
            await self._send_json({"kind": "error", "error": f"{type(exc).__name__}: {exc}"})

    async def _send_loop(self) -> None:
        try:
            while True:
                data = await self.sink.queue.get()
                try:
                    async with self._send_lock:
                        await self.ws.send(data)
                except Exception:
                    break
                finally:
                    self.sink.queue.task_done()
        except asyncio.CancelledError:
            pass

    async def _set_permission_mode(self, mode: str) -> None:
        if self.remote:
            await self.controller.update_permission_mode(mode)
            return
        self.controller.set_permission_mode(mode)

    async def _connect_remote(self, message: dict[str, Any]) -> None:
        from reasonix.remote.client import OpenCodeClient, RemoteConfig
        from reasonix.remote.controller import RemoteController

        if self._workflow_is_running() or self.controller.session.state.value != "idle":
            raise ValueError("Finish or stop the current task before changing execution target")
        config = RemoteConfig(
            url=str(message.get("url", "")).strip(),
            directory=str(message.get("directory", "")).strip(),
            username=str(message.get("username", "opencode")),
            password=str(message.get("password", "")),
        )
        controller = RemoteController(
            OpenCodeClient(config),
            self.sink,
            SessionStore(default_history_path()),
        )
        try:
            await controller.connect(str(message.get("session_id", "")).strip())
        except Exception:
            await controller.close()
            raise
        if self.remote:
            await self.controller.close()
        else:
            self._local_controller = self.controller
        self.controller = controller
        self.remote = {
            "url": config.url,
            "directory": config.directory,
            "version": controller.version,
            "connected": True,
        }

    async def _disconnect_remote(self) -> None:
        if not self.remote:
            return
        if self._workflow_is_running():
            raise ValueError("Stop the workflow before detaching its execution target")
        await self.controller.close()
        self.controller = self._local_controller
        self._local_controller = None
        self.remote = None

    def _experiments(self) -> Any:
        from reasonix.experiments.store import ExperimentStore

        if self._experiment_store is None:
            self._experiment_store = ExperimentStore(default_history_path())
        return self._experiment_store

    async def _experiment_action(self, action: str, message: dict[str, Any]) -> None:
        from reasonix.experiments.service import ExperimentService

        if not self.remote:
            raise ValueError("Connect to the remote OpenCode server first")
        if self._workflow_is_running() or self.controller.session.state.value != "idle":
            raise ValueError("Wait for the agent turn to finish before operating an experiment")
        service = ExperimentService(self.controller.client, self._experiments())
        if action == "submit_experiment":
            if message.get("confirmed") is not True:
                raise ValueError("Explicit confirmation is required to run a remote command")
            await service.submit(
                self.controller.session.id,
                str(message.get("name", "")),
                str(message.get("command", "")),
                str(message.get("config_path", "")),
            )
        else:
            await service.refresh(
                str(message.get("experiment_id", "")),
                stop=action == "stop_experiment",
            )
        await self.controller.refresh()

    async def _send_json(self, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        async with self._send_lock:
            await self.ws.send(data)

    async def send_status(self) -> None:
        tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "read_only": tool.read_only,
                "source": "mcp" if tool.description.startswith("[MCP") else "builtin",
            }
            for tool in sorted(self.controller.opts.registry.all(), key=lambda item: item.name)
        ]
        mcp_servers = [
            {
                "name": status.name,
                "transport": status.transport,
                "state": status.state,
                "tool_count": status.tool_count,
                "error": status.error,
            }
            for status in getattr(self.controller.opts, "mcp_statuses", [])
        ]
        session_records = (
            self.controller.list_sessions() if hasattr(self.controller, "list_sessions") else []
        )
        workflows = (
            self.controller.list_workflows() if hasattr(self.controller, "list_workflows") else []
        )
        history_messages = list(getattr(self.controller, "history_messages", []))
        change_records = list(getattr(self.controller, "latest_changes", []))
        recent_changes = [
            build_change(
                record.path,
                record.old_content,
                record.new_content,
                record.description,
            )
            for record in change_records
        ]
        session_messages = []
        for index, message in enumerate(history_messages):
            role = message.role.value
            if role == "assistant" and not message.content:
                continue
            if role not in {"user", "assistant", "tool"}:
                continue
            session_messages.append(
                {
                    "id": f"history-{index}",
                    "role": role,
                    "text": message.content,
                    "tool_name": message.name,
                }
            )
        await self._send_json(
            {
                "kind": "status",
                "status": {
                    "workspace": self.controller.opts.workspace if self.remote else str(Path.cwd()),
                    "remote": (
                        {
                            **self.remote,
                            "connected": self.controller.connected,
                            "session_id": self.controller.session.id,
                        }
                        if self.remote
                        else None
                    ),
                    "experiments": self._experiments().list(
                        self.remote["url"].rstrip("/"),
                        self.remote["directory"],
                    )
                    if self.remote
                    else [],
                    "session_id": self.controller.session.id,
                    "session_state": self.controller.session.state.value,
                    "permission_mode": self.controller.permission_mode,
                    "provider": {
                        "configured": not bool(self.controller.opts.configuration_error),
                        "name": self.controller.opts.provider_name,
                        "model": self.controller.opts.provider_model,
                        "error": self.controller.opts.configuration_error,
                    },
                    "security": {
                        "required": getattr(self.controller.opts, "security_required", False),
                        "connected": getattr(self.controller.opts, "security_client", None)
                        is not None,
                        "backend": (
                            "remote-opencode"
                            if self.remote
                            else (
                                "java-job-object"
                                if getattr(self.controller.opts, "security_client", None)
                                is not None
                                else "python-direct"
                            )
                        ),
                        "error": getattr(self.controller.opts, "security_error", ""),
                    },
                    "tool_count": len(tools),
                    "tools": tools,
                    "mcp_servers": mcp_servers,
                    "skills": [
                        {
                            "name": skill.name,
                            "description": skill.description,
                            "path": skill.path,
                            "scope": skill.scope,
                        }
                        for skill in getattr(self.controller.opts, "skills", [])
                    ],
                    "sessions": [
                        {
                            "id": record.id,
                            "title": record.title,
                            "workspace": record.workspace,
                            "created_at": record.created_at,
                            "updated_at": record.updated_at,
                            "status": record.status,
                            "last_error": record.last_error,
                            "active": record.id == self.controller.session.id,
                        }
                        for record in session_records
                    ],
                    "session_messages": session_messages,
                    "recovery_prompt": getattr(self.controller, "recovery_prompt", ""),
                    "can_undo": bool(recent_changes),
                    "recent_changes": [
                        {
                            "path": change.path,
                            "description": change.description,
                            "unified_diff": change.unified_diff,
                            "added": change.added,
                            "removed": change.removed,
                        }
                        for change in recent_changes
                    ],
                    "workflows": [
                        {
                            "id": workflow.id,
                            "name": workflow.name,
                            "steps": workflow.steps,
                            "updated_at": workflow.updated_at,
                        }
                        for workflow in workflows
                    ],
                    "workflow_run": self._workflow_run,
                    "pending_questions": [
                        {"id": request_id, "questions": [asdict(q) for q in questions]}
                        for request_id, questions in getattr(
                            self.controller,
                            "pending_questions",
                            {},
                        ).items()
                    ],
                    "pending_approvals": [
                        {
                            "id": approval.id,
                            "tool_name": approval.tool_name,
                            "subject": approval.subject,
                            "args_json": approval.args_json,
                        }
                        for approval in self.controller.pending_approvals
                    ],
                },
            }
        )

    def _workflow_is_running(self, workflow_id: str = "") -> bool:
        return bool(
            self._workflow_task
            and not self._workflow_task.done()
            and (not workflow_id or (self._workflow_run or {}).get("workflow_id") == workflow_id)
        )

    def _start_workflow(self, workflow_id: str) -> None:
        if not workflow_id:
            raise ValueError("workflow_id is required")
        if self._workflow_is_running():
            raise ValueError("Another workflow is already running")
        workflows = self.controller.list_workflows()
        workflow = next((item for item in workflows if item.id == workflow_id), None)
        if workflow is None:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        if self.controller.session.state.value != "idle":
            raise ValueError("Wait for the current turn to finish")
        self._workflow_run = {
            "workflow_id": workflow.id,
            "name": workflow.name,
            "state": "running",
            "current_step": 0,
            "steps": [
                {"prompt": prompt, "state": "pending", "error": ""} for prompt in workflow.steps
            ],
        }
        self._workflow_task = asyncio.create_task(self._run_workflow(workflow))

    async def _run_workflow(self, workflow: Any) -> None:
        assert self._workflow_run is not None
        try:
            for index, prompt in enumerate(workflow.steps):
                self._workflow_run["current_step"] = index
                step = self._workflow_run["steps"][index]
                step["state"] = "running"
                self.sink.emit(
                    Event(
                        kind=Kind.NOTICE,
                        text=(
                            f"工作流“{workflow.name}”正在执行步骤 "
                            f"{index + 1}/{len(workflow.steps)}。"
                        ),
                    )
                )
                await self.send_status()
                await self.controller.send(prompt)
                await self.controller.wait_for_turn()
                if self.controller.last_error:
                    step["state"] = "failed"
                    step["error"] = self.controller.last_error
                    self._workflow_run["state"] = "failed"
                    return
                step["state"] = "completed"
            self._workflow_run["state"] = "completed"
            self.sink.emit(Event(kind=Kind.NOTICE, text=f"工作流“{workflow.name}”已完成。"))
        except asyncio.CancelledError:
            self._workflow_run["state"] = "cancelled"
            current = int(self._workflow_run.get("current_step", 0))
            steps = self._workflow_run.get("steps", [])
            if current < len(steps) and steps[current]["state"] == "running":
                steps[current]["state"] = "cancelled"
        except Exception as exc:
            logger.exception("Workflow execution failed")
            self._workflow_run["state"] = "failed"
            current = int(self._workflow_run.get("current_step", 0))
            steps = self._workflow_run.get("steps", [])
            if current < len(steps):
                steps[current]["state"] = "failed"
                steps[current]["error"] = str(exc)
        finally:
            await self.send_status()

    async def _cancel_workflow(self) -> None:
        task = self._workflow_task
        if not task or task.done():
            return
        await self.controller.cancel()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        if self._runtime:
            self._runtime.detach(self)
            if self._send_task:
                self._send_task.cancel()
                await asyncio.gather(self._send_task, return_exceptions=True)
            return
        await self._cancel_workflow()
        if self._send_task:
            self._send_task.cancel()
        if self.controller is not None:
            await self.controller.close()
        if self._local_controller is not None:
            await self._local_controller.close()


class DesktopRuntime:
    """Own execution for the bridge lifetime, independently of UI sockets.

    One bridge shares one selected session across authenticated views. This is
    process-local ownership, not a clustered scheduler or crash auto-retry.
    """

    def __init__(self) -> None:
        self.clients: set[BridgeClient] = set()
        self.owner = BridgeClient(_BroadcastSocket(self))
        self._lock = asyncio.Lock()
        self._events: deque[str] = deque(maxlen=4096)

    async def start(self) -> None:
        await self.owner.start()

    async def attach(self, client: BridgeClient) -> None:
        async with self._lock:
            await self.owner._ensure_controller()
            await self.owner.sink.queue.join()
            self.clients.add(client)
            await self.owner.send_status()
            # Only replay transient output while a turn is active. Finished
            # turns come from SQLite/remote history and must not be appended twice.
            if self.owner.controller.session.state.value != "idle":
                for data in self._events:
                    client.sink.queue.put_nowait(data)

    def detach(self, client: BridgeClient) -> None:
        self.clients.discard(client)

    async def handle_message(self, raw: str) -> None:
        async with self._lock:
            await self.owner.handle_message(raw)

    async def close(self) -> None:
        await self.owner.close()


class _BroadcastSocket:
    def __init__(self, runtime: DesktopRuntime) -> None:
        self.runtime = runtime

    async def send(self, data: str) -> None:
        event = json.loads(data)
        kind = event.get("kind")
        if kind == "turn_started":
            self.runtime._events.clear()
        if kind == "history_committed":
            self.runtime._events.clear()
            return
        if kind not in {"status", "workspace_suggestions"}:
            self.runtime._events.append(data)
        for client in tuple(self.runtime.clients):
            try:
                client.sink.queue.put_nowait(data)
            except asyncio.QueueFull:
                self.runtime.detach(client)
                # A slow view must reconnect from history rather than consume
                # unbounded RAM or stop another view's agent execution.
                await client.ws.close(code=1013, reason="Reconnect to resync session history")


async def run_server(
    host: str = "127.0.0.1",
    port: int = 9092,
    required_token: str | None = None,
) -> None:
    import websockets

    # Electron injects a fresh random token per launch. When absent (CLI/dev
    # mode) the bridge stays open so local development keeps working; the
    # packaged desktop always supplies a token.
    if required_token is None:
        required_token = os.environ.get("AXIOM_SECURITY_TOKEN", "").strip()

    logger.info("Axiom desktop bridge starting at ws://%s:%s", host, port)
    runtime = DesktopRuntime()
    # Only startup may classify old running records as interrupted. Opening a
    # second store for a remote connection must not corrupt a live local session.
    SessionStore(default_history_path(), recover_running=True)
    await runtime.start()

    async def handler(websocket: Any) -> None:
        client = await BridgeClient.create(
            websocket,
            required_token=required_token,
            runtime=runtime,
        )
        await client.start()
        try:
            async for raw in websocket:
                await client.handle_message(raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            await client.close()

    stopped = asyncio.Event()
    parent_pid_text = os.environ.get("REASONIX_PARENT_PID", "").strip()
    parent_pid = int(parent_pid_text) if parent_pid_text.isdigit() else 0
    watcher = asyncio.create_task(_watch_parent(parent_pid, stopped)) if parent_pid > 0 else None
    try:
        async with websockets.serve(handler, host, port):
            if watcher:
                await stopped.wait()
            else:
                await asyncio.Future()
    finally:
        if watcher:
            watcher.cancel()
        await runtime.close()


async def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9092)
    args = parser.parse_args()
    print(f"Axiom desktop bridge: ws://{args.host}:{args.port}")
    await run_server(args.host, args.port)


if __name__ == "__main__":
    asyncio.run(main())
