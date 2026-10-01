"""Translate remote OpenCode sessions into Axiom's controller/event contract."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import quote

from reasonix.control.controller import Controller, ControllerOptions, Session, SessionState
from reasonix.event import ApprovalRequest, AskQuestion, Event, Kind, Sink, ToolCallInfo
from reasonix.history import SessionRecord, SessionStore
from reasonix.provider import Message, Role
from reasonix.tool.registry import RegistrySnapshot

from .client import OpenCodeClient, RemoteError


class RemoteController(Controller):
    def __init__(self, client: OpenCodeClient, sink: Sink, store: SessionStore) -> None:
        super().__init__(
            ControllerOptions(
                registry=RegistrySnapshot(),
                sink=sink,
                history_store=store,
                workspace=client.config.directory,
                provider_name="OpenCode remote",
            )
        )
        self.client = client
        self.version = ""
        self._remote_sessions: list[SessionRecord] = []
        self._remote_approvals: dict[str, ApprovalRequest] = {}
        self._remote_questions: dict[str, list[AskQuestion]] = {}
        self._session_ids: set[str] = set()
        self._part_text: dict[str, str] = {}
        self._part_types: dict[str, str] = {}
        self._tool_states: dict[str, str] = {}
        self._remote_mode = "ask"
        self._listener: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()

    async def connect(self, session_id: str = "") -> None:
        self.version = str((await self.client.health()).get("version", ""))
        if session_id:
            await self.resume_session(session_id)
        else:
            await self.new_session()
        self._listener = asyncio.create_task(self._listen())
        await asyncio.wait_for(self._ready.wait(), timeout=15)

    async def new_session(self) -> None:
        if self.session.state != SessionState.IDLE:
            raise ValueError("Finish or stop the remote task before changing sessions")
        await self._adopt(await self.client.create_session())

    async def resume_session(self, session_id: str) -> None:
        if self.session.state != SessionState.IDLE:
            raise ValueError("Finish or stop the remote task before changing sessions")
        result = await self.client.request("GET", self.client.session_path(session_id))
        await self._adopt(result)

    async def _adopt(self, info: dict[str, Any]) -> None:
        self.session = Session(
            id=str(info["id"]),
            title=str(info.get("title", "Remote session")),
            created_at=float(info.get("time", {}).get("created", time.time() * 1000)) / 1000,
        )
        self._session_ids = {self.session.id}
        self._part_text.clear()
        self._part_types.clear()
        self._tool_states.clear()
        self._remote_approvals.clear()
        self._remote_questions.clear()
        self._remote_mode = "ask"
        self._create_session_record()
        await self.refresh()

    async def refresh(self) -> None:
        rows = await self.client.request(
            "GET", self.client.session_path(self.session.id, "/message")
        )
        messages: list[Message] = []
        for row in rows:
            info = row.get("info", {})
            parts = row.get("parts", [])
            role = Role.USER if info.get("role") == "user" else Role.ASSISTANT
            text = "\n".join(
                str(part.get("text", "")) for part in parts if part.get("type") == "text"
            )
            if text:
                messages.append(Message(role=role, content=text))
            for part in parts:
                if part.get("type") in {"text", "reasoning"}:
                    self._part_text[str(part.get("id", ""))] = str(part.get("text", ""))
                    self._part_types[str(part.get("id", ""))] = str(part["type"])
                if part.get("type") == "tool":
                    state = part.get("state", {})
                    if state.get("status") in {"completed", "error"}:
                        messages.append(
                            Message(
                                role=Role.TOOL,
                                name=str(part.get("tool", "")),
                                tool_call_id=str(part.get("callID", "")),
                                content=str(state.get("output", state.get("error", ""))),
                            )
                        )
        self._history = messages
        if self.opts.history_store:
            self.opts.history_store.save_messages(self.session.id, messages)
        statuses = await self.client.request("GET", "/session/status")
        busy = statuses.get(self.session.id, {}).get("type") in {"busy", "retry"}
        self.session.state = SessionState.RUNNING if busy else SessionState.IDLE
        for info in await self.client.request(
            "GET", self.client.session_path(self.session.id, "/children")
        ):
            self._session_ids.add(str(info["id"]))
        pending = await self.client.request("GET", "/permission")
        self._remote_approvals.clear()
        for item in pending:
            if item.get("sessionID") in self._session_ids:
                self._permission(item, emit=False)
        self._remote_questions.clear()
        for item in await self.client.request("GET", "/question"):
            if item.get("sessionID") in self._session_ids:
                self._question(item, emit=False)
        self._remote_sessions = [
            SessionRecord(
                id=str(item["id"]),
                title=str(item.get("title", "Remote session")),
                workspace=self.opts.workspace,
                created_at=float(item.get("time", {}).get("created", 0)) / 1000,
                updated_at=float(item.get("time", {}).get("updated", 0)) / 1000,
                status="running" if item["id"] in statuses else "idle",
            )
            for item in await self.client.request("GET", "/session")
        ]

    async def send(self, text: str) -> None:
        if self.session.state != SessionState.IDLE:
            raise ValueError("Wait for the remote turn to finish, or stop it first")
        if not self._ready.is_set():
            raise RemoteError("Remote event stream is reconnecting; prompt was not sent")
        self._turn_done.clear()
        self._last_error = ""
        self.session.state = SessionState.RUNNING
        self._sink.emit(Event(kind=Kind.TURN_STARTED))
        try:
            await self.client.prompt(self.session.id, text)
        except RemoteError:
            # A failed HTTP response does not prove the prompt was never admitted.
            # Refresh the server state and require an explicit user retry.
            await self.refresh()
            self._turn_done.set()
            raise

    async def cancel(self) -> None:
        await self.client.request("POST", self.client.session_path(self.session.id, "/abort"))
        self.session.state = SessionState.IDLE
        self._turn_done.set()
        self._sink.emit(Event(kind=Kind.TURN_DONE))
        await self.refresh()

    @property
    def permission_mode(self) -> str:
        return self._remote_mode

    async def update_permission_mode(self, mode: str) -> None:
        if mode not in {"ask", "allow", "deny"}:
            raise ValueError("Permission mode must be ask, allow or deny")
        await self.client.request(
            "PATCH",
            self.client.session_path(self.session.id),
            {
                "permission": self.client.permissions(mode),
            },
        )
        self._remote_mode = mode

    @property
    def pending_approvals(self) -> list[ApprovalRequest]:
        return list(self._remote_approvals.values())

    @property
    def pending_questions(self) -> dict[str, list[AskQuestion]]:
        return dict(self._remote_questions)

    @property
    def connected(self) -> bool:
        return self._ready.is_set()

    def list_sessions(self) -> list[SessionRecord]:
        return self._remote_sessions

    async def approve(self, request_id: str, allow: bool, scope: str = "once") -> None:
        if request_id not in self._remote_approvals:
            raise ValueError("Unknown remote permission request")
        reply = "always" if allow and scope == "session" else "once" if allow else "reject"
        await self.client.request(
            "POST", f"/permission/{quote(request_id, safe='')}/reply", {"reply": reply}
        )
        self._remote_approvals.pop(request_id, None)

    async def approve_all(self, allow: bool, scope: str = "once") -> int:
        ids = list(self._remote_approvals)
        for request_id in ids:
            await self.approve(request_id, allow, scope)
        return len(ids)

    async def answer_ask(self, ask_id: str, answers: list[str]) -> None:
        if ask_id not in self._remote_questions:
            raise ValueError("Unknown remote question")
        await self.client.request(
            "POST",
            f"/question/{quote(ask_id, safe='')}/reply",
            {
                "answers": [[answer] for answer in answers],
            },
        )
        self._remote_questions.pop(ask_id, None)

    async def delete_session(self, session_id: str) -> bool:
        if session_id == self.session.id:
            raise ValueError("Cannot delete the active remote session")
        await self.client.request("DELETE", self.client.session_path(session_id))
        await self.refresh()
        return True

    async def undo_last_turn(self) -> int:
        raise ValueError("Local file undo is unavailable for a remote OpenCode session")

    async def close(self) -> None:
        # Detaching the client must never abort GPU work on the remote server.
        if self._listener:
            self._listener.cancel()
            await asyncio.gather(self._listener, return_exceptions=True)
        await self.client.close()

    async def _listen(self) -> None:
        failures = 0
        while True:
            try:
                async for payload in self.client.events():
                    if payload.get("type") == "server.connected":
                        await self.refresh()
                        self._ready.set()
                        failures = 0
                        if self.session.state == SessionState.IDLE:
                            self._turn_done.set()
                    await self.handle_event(payload)
                raise RemoteError("Remote event stream closed")
            except (RemoteError, TimeoutError) as exc:
                self._ready.clear()
                failures += 1
                self._sink.emit(Event(kind=Kind.NOTICE, text=f"{exc}; reconnecting ({failures}/5)"))
                if failures >= 5:
                    self._last_error = str(exc)
                    self._sink.emit(Event(kind=Kind.ERROR, error=str(exc)))
                    self._turn_done.set()
                    return
                await asyncio.sleep(min(2**failures, 30))

    def _permission(self, properties: dict[str, Any], *, emit: bool = True) -> None:
        request = ApprovalRequest(
            id=str(properties["id"]),
            tool_name=str(properties.get("permission", "tool")),
            subject=", ".join(properties.get("patterns", [])),
            args_json=json.dumps(properties.get("metadata", {}), ensure_ascii=False),
        )
        self._remote_approvals[request.id] = request
        if emit:
            self._sink.emit(Event(kind=Kind.APPROVAL_REQUEST, approval=request))

    def _question(self, properties: dict[str, Any], *, emit: bool = True) -> None:
        questions = [
            AskQuestion(
                header=str(item.get("header", "")),
                question=str(item.get("question", "")),
                options=[str(option.get("label", "")) for option in item.get("options", [])],
                multi_select=bool(item.get("multiple", False)),
            )
            for item in properties.get("questions", [])
        ]
        request_id = str(properties["id"])
        self._remote_questions[request_id] = questions
        if emit:
            self._sink.emit(
                Event(
                    kind=Kind.ASK_REQUEST,
                    ask_id=request_id,
                    ask_questions=questions,
                )
            )

    async def handle_event(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type", "")
        properties = payload.get("properties", {})
        if event_type == "session.created":
            info = properties.get("info", {})
            if info.get("parentID") in self._session_ids:
                self._session_ids.add(str(info["id"]))
            return
        part = properties.get("part", {})
        session_id = properties.get("sessionID", part.get("sessionID", ""))
        if session_id not in self._session_ids:
            return
        if event_type == "permission.asked":
            self._permission(properties)
        elif event_type == "permission.replied":
            self._remote_approvals.pop(str(properties.get("requestID", "")), None)
        elif event_type == "question.asked":
            self._question(properties)
        elif event_type in {"question.replied", "question.rejected"}:
            self._remote_questions.pop(str(properties.get("requestID", "")), None)
        elif event_type == "session.error":
            self._last_error = "Remote session failed; inspect the remote server logs"
            self._sink.emit(Event(kind=Kind.ERROR, error=self._last_error))
        elif event_type == "session.status" and session_id == self.session.id:
            if properties.get("status", {}).get("type") == "idle":
                await self.refresh()
                self._turn_done.set()
                self._sink.emit(Event(kind=Kind.TURN_DONE))
            else:
                self.session.state = SessionState.RUNNING
        elif event_type == "message.part.delta" and session_id == self.session.id:
            delta = str(properties.get("delta", ""))
            part_id = str(properties.get("partID", ""))
            self._part_text[part_id] = self._part_text.get(part_id, "") + delta
            reasoning = self._part_types.get(part_id) == "reasoning"
            self._sink.emit(
                Event(
                    kind=Kind.REASONING if reasoning else Kind.TEXT,
                    text="" if reasoning else delta,
                    reasoning=delta if reasoning else "",
                )
            )
        elif event_type == "message.part.updated":
            if part.get("type") == "tool":
                call_id = str(part.get("callID", part.get("id", "")))
                state = part.get("state", {})
                status = str(state.get("status", ""))
                if self._tool_states.get(call_id) == status:
                    return
                self._tool_states[call_id] = status
                if status in {"running", "completed", "error"}:
                    info = ToolCallInfo(
                        id=call_id,
                        name=str(part.get("tool", "")),
                        args_json=json.dumps(state.get("input", {}), ensure_ascii=False),
                        output=str(state.get("output", "")),
                        error=state.get("error"),
                    )
                    self._sink.emit(
                        Event(
                            kind=Kind.TOOL_DISPATCH if status == "running" else Kind.TOOL_RESULT,
                            tool=info,
                        )
                    )
            elif part.get("type") in {"text", "reasoning"} and session_id == self.session.id:
                part_id = str(part.get("id", ""))
                self._part_types[part_id] = str(part["type"])
                text = str(part.get("text", ""))
                previous = self._part_text.get(part_id, "")
                self._part_text[part_id] = text
                if text.startswith(previous) and len(text) > len(previous):
                    self._sink.emit(
                        Event(
                            kind=Kind.TEXT if part["type"] == "text" else Kind.REASONING,
                            text=text[len(previous) :],
                        )
                    )
