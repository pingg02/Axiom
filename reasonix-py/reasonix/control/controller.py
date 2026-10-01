"""Transport-independent session controller."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any

from reasonix.agent.runner import Runner, RunnerOptions, TurnBudget
from reasonix.diff import Change
from reasonix.event import ApprovalRequest, AskQuestion, Event, Kind, Sink
from reasonix.grpc import SecurityClient
from reasonix.history import ChangeRecord, SessionRecord, SessionStore, WorkflowRecord
from reasonix.memory import MemorySet
from reasonix.permission.permission import ApprovalScope, Decision, Gate
from reasonix.provider import Message, Provider, ToolCall
from reasonix.tool.registry import RegistrySnapshot


class SessionState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_ASK = "awaiting_ask"
    CANCELLED = "cancelled"


@dataclass
class Session:
    id: str = ""
    title: str = "New session"
    created_at: float = 0.0
    state: SessionState = SessionState.IDLE


@dataclass
class ControllerOptions:
    registry: RegistrySnapshot
    provider: Provider | None = None
    memory: MemorySet | None = None
    sink: Sink | None = None
    max_steps: int = 50
    max_subagent_depth: int = 2
    subagent_steps: int = 10
    temperature: float = 0.0
    language: str = ""
    additional_prompt: str = ""
    instructions: str = ""
    permission_gate: Gate | None = None
    resources: list[Any] = field(default_factory=list)
    mcp_statuses: list[Any] = field(default_factory=list)
    skills: list[Any] = field(default_factory=list)
    provider_name: str = ""
    provider_model: str = ""
    configuration_error: str = ""
    history_store: SessionStore | None = None
    workspace: str = ""
    security_client: SecurityClient | None = None
    security_required: bool = False
    security_error: str = ""


class Controller:
    """Own one chat session and its interactive approval state."""

    def __init__(self, opts: ControllerOptions) -> None:
        self.opts = opts
        self.session = Session(id=str(uuid.uuid4()), created_at=time.time())
        self._sink = opts.sink or _NoopSink()
        self._provider = opts.provider
        self._history: list[Message] = []
        self._current_turn_id = ""
        self._turn_budget = TurnBudget(opts.max_steps)
        self._last_error = ""
        self._turn_done = asyncio.Event()
        self._turn_task: asyncio.Task[None] | None = None
        self._cancel_flag = False
        self._last_error = ""
        self._approval_futures: dict[str, asyncio.Future[tuple[bool, ApprovalScope]]] = {}
        self._approval_requests: dict[str, ApprovalRequest] = {}
        self._ask_futures: dict[str, asyncio.Future[list[str]]] = {}
        self._ask_questions: dict[str, list[AskQuestion]] = {}
        self._initial_permission_mode = (
            self.opts.permission_gate.policy.mode if self.opts.permission_gate else Decision.ALLOW
        )
        if self.opts.permission_gate and self.opts.permission_gate.approver is None:
            self.opts.permission_gate.approver = _ControllerApprover(self)
        self._create_session_record()

    async def send(self, text: str) -> None:
        if self.session.state != SessionState.IDLE:
            self._sink.emit(
                Event(
                    kind=Kind.NOTICE,
                    level="warning",
                    text=f"Session is {self.session.state.value}; finish or cancel it first.",
                )
            )
            return
        if self.opts.provider is None:
            self._sink.emit(Event(kind=Kind.ERROR, error="No model provider is configured."))
            self._turn_done.set()
            return

        self._cancel_flag = False
        self._last_error = ""
        self._turn_done.clear()
        self.session.state = SessionState.RUNNING
        if self.session.title == "New session":
            self.session.title = _session_title(text)
            if self.opts.history_store:
                self.opts.history_store.set_title(self.session.id, self.session.title)
        if self.opts.history_store:
            self._history = self.opts.history_store.reconcile_interrupted_tools(self.session.id)
            self.opts.history_store.save_checkpoint(
                self.session.id,
                text,
                self._history,
            )
        self._current_turn_id = str(uuid.uuid4())
        self._turn_budget = TurnBudget(self.opts.max_steps)
        runner = Runner(
            RunnerOptions(
                sink=self._sink,
                registry=self.opts.registry,
                provider=self.opts.provider,
                memory=self.opts.memory,
                instructions=self.opts.instructions,
                additional_prompt=self.opts.additional_prompt,
                language=self.opts.language,
                max_steps=self.opts.max_steps,
                temperature=self.opts.temperature,
                ask_callback=self.ask_user,
                permission_gate=self.opts.permission_gate,
                history=list(self._history),
                change_callback=self._record_change,
                progress_callback=self._save_progress,
                tool_state_callback=self._record_tool,
                task_callback=lambda args: self._run_subagent(args, 1),
                budget=self._turn_budget,
                security_client=self.opts.security_client,
                security_required=self.opts.security_required,
                workspace=self.opts.workspace,
            )
        )
        self._turn_task = asyncio.create_task(self._run_turn(runner, text))

    async def cancel(self) -> None:
        self._cancel_flag = True
        self._cancel_pending_prompts()
        if self._turn_task and not self._turn_task.done():
            self._turn_task.cancel()
            self._sink.emit(Event(kind=Kind.NOTICE, level="info", text="Turn cancelled by user."))
            self._sink.emit(Event(kind=Kind.TURN_DONE))
            await asyncio.gather(self._turn_task, return_exceptions=True)
        self.session.state = SessionState.IDLE
        if self.opts.history_store:
            self.opts.history_store.set_status(self.session.id, "cancelled")

    async def approve(self, request_id: str, allow: bool, scope: str = "once") -> None:
        future = self._approval_futures.pop(request_id, None)
        self._approval_requests.pop(request_id, None)
        if future and not future.done():
            try:
                approval_scope = ApprovalScope(scope)
            except ValueError:
                approval_scope = ApprovalScope.ONCE
            future.set_result((allow, approval_scope))
        self._sync_interactive_state()

    async def approve_all(self, allow: bool, scope: str = "once") -> int:
        """Resolve every approval currently pending for this session."""
        request_ids = list(self._approval_futures)
        for request_id in request_ids:
            await self.approve(request_id, allow, scope)
        return len(request_ids)

    @property
    def pending_approvals(self) -> list[ApprovalRequest]:
        return list(self._approval_requests.values())

    @property
    def pending_questions(self) -> dict[str, list[AskQuestion]]:
        return dict(self._ask_questions)

    @property
    def history_messages(self) -> list[Message]:
        return list(self._history)

    @property
    def recovery_prompt(self) -> str:
        if not self.opts.history_store:
            return ""
        return self.opts.history_store.checkpoint_prompt(self.session.id)

    def list_sessions(self) -> list[SessionRecord]:
        if not self.opts.history_store:
            return []
        return self.opts.history_store.list_sessions()

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def latest_changes(self) -> list[ChangeRecord]:
        if not self.opts.history_store:
            return []
        return self.opts.history_store.latest_changes(self.session.id)

    @property
    def permission_mode(self) -> str:
        gate = self.opts.permission_gate
        return gate.policy.mode.value if gate else Decision.ALLOW.value

    def set_permission_mode(self, mode: str) -> str:
        """Set the fallback posture for future writer calls in this session."""
        gate = self.opts.permission_gate
        if gate is None:
            return Decision.ALLOW.value
        gate.policy.mode = Decision(mode)
        return gate.policy.mode.value

    async def answer_ask(self, ask_id: str, answers: list[str]) -> None:
        future = self._ask_futures.pop(ask_id, None)
        self._ask_questions.pop(ask_id, None)
        if future and not future.done():
            future.set_result([str(answer) for answer in answers])
            self.session.state = SessionState.RUNNING

    async def ask_user(self, questions: list[AskQuestion]) -> list[str]:
        ask_id = str(uuid.uuid4())
        future: asyncio.Future[list[str]] = asyncio.get_running_loop().create_future()
        self._ask_futures[ask_id] = future
        self._ask_questions[ask_id] = questions
        self.session.state = SessionState.AWAITING_ASK
        self._sink.emit(
            Event(
                kind=Kind.ASK_REQUEST,
                ask_id=ask_id,
                ask_questions=questions,
                text="User input required.",
            )
        )
        answers = await future
        if self.session.state == SessionState.AWAITING_ASK:
            self.session.state = SessionState.RUNNING
        return list(answers)

    async def new_session(self) -> None:
        if self.session.state != SessionState.IDLE:
            await self.cancel()
        if self.opts.permission_gate:
            self.opts.permission_gate.policy.mode = self._initial_permission_mode
            self.opts.permission_gate.policy.session_allow.clear()
        self.session = Session(id=str(uuid.uuid4()), created_at=time.time())
        self._history = []
        self._current_turn_id = ""
        self._create_session_record()

    async def resume_session(self, session_id: str) -> None:
        if not self.opts.history_store:
            raise ValueError("Session history is not configured")
        record = self.opts.history_store.get_session(session_id)
        if record is None:
            raise ValueError(f"Unknown session: {session_id}")
        if self.session.state != SessionState.IDLE:
            await self.cancel()
        if self.opts.permission_gate:
            self.opts.permission_gate.policy.mode = self._initial_permission_mode
            self.opts.permission_gate.policy.session_allow.clear()
        self.session = Session(
            id=record.id,
            title=record.title,
            created_at=record.created_at,
            state=SessionState.IDLE,
        )
        self._history = self.opts.history_store.reconcile_interrupted_tools(session_id)
        self._current_turn_id = ""
        self.opts.history_store.set_status(session_id, "idle")

    async def delete_session(self, session_id: str) -> bool:
        if not self.opts.history_store:
            return False
        if session_id == self.session.id:
            raise ValueError("Cannot delete the active session")
        return self.opts.history_store.delete_session(session_id)

    def list_workflows(self) -> list[WorkflowRecord]:
        if not self.opts.history_store:
            return []
        return self.opts.history_store.list_workflows(self.opts.workspace)

    def save_workflow(self, workflow_id: str, name: str, steps: list[str]) -> None:
        if not self.opts.history_store:
            raise ValueError("Workflow storage is not configured")
        self.opts.history_store.save_workflow(
            workflow_id,
            workspace=self.opts.workspace,
            name=name,
            steps=steps,
        )

    def delete_workflow(self, workflow_id: str) -> bool:
        if not self.opts.history_store:
            return False
        return self.opts.history_store.delete_workflow(
            workflow_id,
            self.opts.workspace,
        )

    async def undo_last_turn(self) -> int:
        """Restore files changed by the latest tool-writing turn.

        Every current file must still match the content written by that turn.
        This prevents undo from overwriting later manual edits.
        """
        if self.session.state != SessionState.IDLE:
            raise ValueError("Wait for the current turn to finish before undoing changes")
        changes = self.latest_changes
        if not changes:
            return 0

        final_contents: dict[Path, str | None] = {}
        virtual_contents: dict[Path, str | None] = {}
        for record in reversed(changes):
            path = Path(record.path).resolve()
            if path in virtual_contents:
                current = virtual_contents[path]
            else:
                current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != record.new_content:
                raise ValueError(f"Cannot undo because the file changed afterwards: {record.path}")
            virtual_contents[path] = record.old_content
            final_contents[path] = record.old_content

        for path, content in final_contents.items():
            if content is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

        turn_id = changes[0].turn_id
        assert self.opts.history_store is not None
        self.opts.history_store.mark_turn_reverted(self.session.id, turn_id)
        return len(changes)

    async def close(self) -> None:
        if self.session.state != SessionState.IDLE:
            await self.cancel()
        for resource in self.opts.resources:
            closer = getattr(resource, "aclose", None) or getattr(resource, "close", None)
            if closer is None:
                continue
            result = closer()
            if asyncio.iscoroutine(result):
                await result

    async def wait_for_turn(self) -> None:
        await self._turn_done.wait()

    async def _run_turn(self, runner: Runner, text: str) -> None:
        try:
            if self._cancel_flag:
                return
            result = await runner.run(text)
            self._history = result.messages
            if self.opts.history_store:
                self.opts.history_store.save_messages(self.session.id, self._history)
            if result.error:
                self._last_error = result.error
                self._sink.emit(Event(kind=Kind.ERROR, error=result.error))
                if self.opts.history_store:
                    self.opts.history_store.set_status(self.session.id, "failed", result.error)
            elif self.opts.history_store:
                self.opts.history_store.clear_checkpoint(self.session.id)
                self.opts.history_store.set_status(self.session.id, "idle")
        except asyncio.CancelledError:
            self._last_error = "cancelled"
            if self.opts.history_store:
                self.opts.history_store.set_status(self.session.id, "cancelled")
        except Exception as exc:
            self._last_error = str(exc)
            self._sink.emit(Event(kind=Kind.ERROR, error=str(exc)))
            self._sink.emit(Event(kind=Kind.TURN_DONE))
            if self.opts.history_store:
                self.opts.history_store.set_status(self.session.id, "interrupted", str(exc))
        finally:
            self.session.state = SessionState.IDLE
            self._turn_task = None
            self._turn_done.set()

    def _create_session_record(self) -> None:
        if self.opts.history_store:
            self.opts.history_store.create_session(
                self.session.id,
                title=self.session.title,
                workspace=self.opts.workspace,
                created_at=self.session.created_at,
            )

    def _record_change(self, tool_call_id: str, change: Change) -> None:
        if not self.opts.history_store or not self._current_turn_id:
            return
        self.opts.history_store.record_change(
            self.session.id,
            self._current_turn_id,
            change,
        )

    def _save_progress(self, messages: list[Message]) -> None:
        self._history = list(messages)
        if self.opts.history_store:
            self.opts.history_store.save_messages(self.session.id, self._history)

    def _record_tool(self, call: ToolCall, state: str, output: str) -> None:
        if self.opts.history_store:
            self.opts.history_store.record_tool(
                self.session.id,
                self._current_turn_id,
                call,
                state,
                output,
            )

    async def _run_subagent(
        self,
        args_json: str,
        depth: int,
        parent_id: str = "",
        parent_turn: str = "",
    ) -> str:
        if depth > self.opts.max_subagent_depth:
            return "Error: maximum sub-agent nesting depth reached."
        args = json.loads(args_json)
        if not isinstance(args, dict) or not isinstance(args.get("prompt"), str):
            return "Error: task requires a string prompt."
        prompt = args["prompt"].strip()
        if not prompt or len(prompt) > 32000:
            return "Error: sub-agent prompt must contain 1-32000 characters."
        provider = self.opts.provider
        if provider is None:
            return "Error: no provider is configured."
        if args.get("subagent_model") not in {
            None,
            "",
            self.opts.provider_model,
            provider.model_name,
        }:
            return (
                "Error: model overrides are not supported; the sub-agent inherits the parent model."
            )
        child_id = str(uuid.uuid4())
        child_turn = str(uuid.uuid4())
        store = self.opts.history_store
        if store:
            store.create_session(
                child_id,
                title="[subagent] " + str(args.get("description", "task"))[:80],
                workspace=self.opts.workspace,
                created_at=time.time(),
            )
            store.link_subagent(
                parent_id or self.session.id,
                parent_turn or self._current_turn_id,
                child_id,
                depth,
            )
            store.save_checkpoint(child_id, prompt, [])

        def progress(messages: list[Message]) -> None:
            if store:
                store.save_messages(child_id, messages)

        def tool_state(call: ToolCall, state: str, output: str) -> None:
            if store:
                store.record_tool(child_id, child_turn, call, state, output)

        def change(call_id: str, change: Change) -> None:
            self._record_change(call_id, change)
            if store:
                store.record_change(child_id, child_turn, change)

        registry = RegistrySnapshot(
            tools={
                name: tool
                for name, tool in self.opts.registry.tools.items()
                if name != "task" or depth < self.opts.max_subagent_depth
            }
        )
        self._sink.emit(
            Event(kind=Kind.NOTICE, text=f"Sub-agent {child_id[:8]} started (depth {depth}).")
        )
        runner = Runner(
            RunnerOptions(
                sink=_SubagentSink(self._sink, child_id),
                registry=registry,
                provider=provider,
                memory=self.opts.memory,
                instructions=self.opts.instructions,
                additional_prompt=self.opts.additional_prompt,
                language=self.opts.language,
                max_steps=min(self.opts.subagent_steps, self.opts.max_steps),
                temperature=self.opts.temperature,
                ask_callback=self.ask_user,
                permission_gate=self.opts.permission_gate,
                change_callback=change,
                progress_callback=progress,
                tool_state_callback=tool_state,
                task_callback=lambda child_args: self._run_subagent(
                    child_args,
                    depth + 1,
                    child_id,
                    child_turn,
                ),
                budget=self._turn_budget,
                security_client=self.opts.security_client,
                security_required=self.opts.security_required,
                workspace=self.opts.workspace,
            )
        )
        try:
            result = await runner.run(prompt)
            if store:
                store.set_status(child_id, "failed" if result.error else "idle", result.error)
                if not result.error:
                    store.clear_checkpoint(child_id)
            if result.error:
                return f"Error: sub-agent {child_id}: {result.error}"
            answer = result.message.content if result.message else ""
            return f"[sub-agent session {child_id}]\n{answer}"
        except asyncio.CancelledError:
            if store:
                store.set_status(child_id, "cancelled")
            raise
        except Exception as exc:
            if store:
                store.set_status(child_id, "interrupted", str(exc))
            raise

    def _cancel_pending_prompts(self) -> None:
        futures: list[asyncio.Future[Any]] = [
            *self._approval_futures.values(),
            *self._ask_futures.values(),
        ]
        self._approval_futures.clear()
        self._approval_requests.clear()
        self._ask_futures.clear()
        self._ask_questions.clear()
        for future in futures:
            if not future.done():
                future.cancel()

    def _sync_interactive_state(self) -> None:
        if self._approval_futures:
            self.session.state = SessionState.AWAITING_APPROVAL
        elif self._ask_futures:
            self.session.state = SessionState.AWAITING_ASK
        elif self._turn_task and not self._turn_task.done():
            self.session.state = SessionState.RUNNING
        else:
            self.session.state = SessionState.IDLE


class _NoopSink:
    def emit(self, event: Event) -> None:
        pass


class _SubagentSink:
    def __init__(self, parent: Sink, child_id: str) -> None:
        self.parent = parent
        self.child_id = child_id

    def emit(self, event: Event) -> None:
        if event.kind in {
            Kind.TURN_STARTED,
            Kind.TURN_DONE,
            Kind.HISTORY_COMMITTED,
            Kind.TEXT,
            Kind.REASONING,
            Kind.MESSAGE,
            Kind.PHASE,
        }:
            return
        if event.tool:
            event = replace(
                event,
                tool=replace(
                    event.tool,
                    id=f"{self.child_id}:{event.tool.id}",
                ),
            )
        self.parent.emit(event)


class _ControllerApprover:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller

    async def approve(
        self,
        tool_name: str,
        subject: str,
        args_json: str,
    ) -> tuple[bool, ApprovalScope]:
        request_id = str(uuid.uuid4())
        future: asyncio.Future[tuple[bool, ApprovalScope]] = (
            asyncio.get_running_loop().create_future()
        )
        self.controller._approval_futures[request_id] = future
        self.controller.session.state = SessionState.AWAITING_APPROVAL
        request = ApprovalRequest(
            id=request_id,
            tool_name=tool_name,
            subject=subject,
            args_json=args_json,
        )
        self.controller._approval_requests[request_id] = request
        self.controller._sink.emit(
            Event(
                kind=Kind.APPROVAL_REQUEST,
                text=f"Approval required for {tool_name}: {subject}",
                approval=request,
            )
        )
        allowed, scope = await future
        self.controller._sync_interactive_state()
        return bool(allowed), scope


def _session_title(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:60] + ("…" if len(compact) > 60 else "")
