"""FastAPI/SSE server for the browser frontend."""

from __future__ import annotations

import asyncio
import inspect
import json
import sys
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from reasonix.boot import build_controller_async as build_controller
from reasonix.config import Config
from reasonix.control.controller import Controller
from reasonix.event import Event, Kind, Sink, event_to_frontend_dict

app = FastAPI(title="Axiom")


class SSESink(Sink):
    """Sink that queues typed events for Server-Sent Events."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self._done = False

    def emit(self, event: Event) -> None:
        if not self._done:
            self.queue.put_nowait(event)

    async def __aiter__(self) -> AsyncGenerator[dict[str, str], None]:
        while True:
            try:
                event = await asyncio.wait_for(self.queue.get(), timeout=300)
            except TimeoutError:
                yield {"event": "timeout", "data": "{}"}
                break

            data = event_to_frontend_dict(event)
            yield {"event": "message", "data": json.dumps(data, ensure_ascii=False)}

            if event.kind == Kind.TURN_DONE:
                yield {"event": "done", "data": "{}"}
                break


@dataclass
class _ChatSession:
    message: str
    sink: SSESink | None = None
    task: asyncio.Task[None] | None = None


class SessionManager:
    """In-memory chat sessions for the browser SSE frontend."""

    def __init__(self) -> None:
        self._sessions: dict[str, _ChatSession] = {}

    def clear(self) -> None:
        self._sessions.clear()

    def create_chat(self, session_id: str, message: str) -> None:
        self._sessions[session_id] = _ChatSession(message=message)

    async def start_stream(
        self, session_id: str
    ) -> tuple[SSESink, asyncio.Task[None]] | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None

        if session.sink is not None and session.task is not None:
            return session.sink, session.task

        sink = SSESink()
        controller_result: Any = build_controller(sink=sink)
        if inspect.isawaitable(controller_result):
            controller_result = await controller_result
        controller = cast(Controller, controller_result)
        task = asyncio.create_task(self._run_chat(controller, session.message, sink))
        session.sink = sink
        session.task = task
        return sink, task

    def close_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def _run_chat(
        self, controller: Controller, message: str, sink: SSESink
    ) -> None:
        try:
            await controller.send(message)
            await controller.wait_for_turn()
        except Exception as exc:
            sink.emit(Event(kind=Kind.ERROR, error=str(exc)))
            sink.emit(Event(kind=Kind.TURN_DONE))
        finally:
            sink._done = True
            await controller.close()


manager = SessionManager()


def _frontend_dist_candidates() -> list[Path]:
    exe_dir = Path(sys.executable).resolve().parent
    repo_root = Path(__file__).resolve().parents[3]
    return [
        exe_dir / "frontend",
        Path.cwd() / "frontend",
        repo_root / "reasonix-build" / "frontend",
        repo_root / "desktop" / "python-frontend" / "dist",
    ]


def _frontend_dist() -> Path | None:
    for candidate in _frontend_dist_candidates():
        if (candidate / "index.html").is_file():
            return candidate
    return None


@app.get("/")
async def index() -> HTMLResponse:
    return HTMLResponse(CHAT_HTML)


@app.get("/desktop")
async def desktop() -> Response:
    frontend_dir = _frontend_dist()
    if frontend_dir:
        return FileResponse(str(frontend_dir / "index.html"))
    return HTMLResponse(
        "<h2>Desktop frontend not built</h2>"
        "<p>Run: cd desktop/python-frontend && npm install && npm run build</p>"
    )


@app.get("/assets/{path:path}")
async def frontend_assets(path: str) -> Response:
    frontend_dir = _frontend_dist()
    if not frontend_dir:
        return JSONResponse({"error": "frontend not built"}, status_code=404)
    asset_path = (frontend_dir / "assets" / path).resolve()
    assets_root = (frontend_dir / "assets").resolve()
    if assets_root not in [asset_path, *asset_path.parents] or not asset_path.is_file():
        return JSONResponse({"error": "asset not found"}, status_code=404)
    return FileResponse(str(asset_path))


@app.post("/chat")
async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    message = body.get("message", "")
    if not message:
        return JSONResponse({"error": "message is required"}, status_code=400)

    session_id = str(uuid.uuid4())
    manager.create_chat(session_id, message)
    return JSONResponse({
        "session_id": session_id,
        "stream_url": f"/stream/{session_id}",
    })


@app.get("/stream/{session_id}")
async def stream(session_id: str) -> Response:
    started = await manager.start_stream(session_id)
    if started is None:
        return JSONResponse({"error": "session not found"}, status_code=404)
    sink, chat_task = started

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        try:
            async for event_data in sink:
                yield event_data
                if event_data.get("event") in ("done", "timeout"):
                    break
            await chat_task
        finally:
            manager.close_session(session_id)

    return EventSourceResponse(event_generator())


CHAT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Reasonix Chat</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, system-ui, sans-serif; background: #1a1a2e; color: #eee; height: 100vh; display: flex; flex-direction: column; }
        #messages { flex: 1; overflow-y: auto; padding: 20px; }
        .msg { margin: 10px 0; padding: 12px; border-radius: 8px; line-height: 1.5; }
        .user { background: #16213e; align-self: flex-end; }
        .assistant { background: #0f3460; }
        .error { background: #4a1a1a; color: #ff6b6b; }
        #input-area { display: flex; padding: 20px; gap: 10px; border-top: 1px solid #333; }
        #input { flex: 1; padding: 12px; border: 1px solid #333; border-radius: 8px; background: #16213e; color: #eee; font-size: 14px; }
        #send { padding: 12px 24px; border: none; border-radius: 8px; background: #0f3460; color: #eee; cursor: pointer; }
        #send:hover { background: #1a4a8a; }
    </style>
</head>
<body>
    <div id="messages">
        <div class="msg assistant">Welcome! Type a message to start.</div>
    </div>
    <div id="input-area">
        <input id="input" type="text" placeholder="Type a message..." autofocus>
        <button id="send" onclick="sendMessage()">Send</button>
    </div>
    <script>
        const messages = document.getElementById('messages');
        const input = document.getElementById('input');
        let currentStream = null;

        input.addEventListener('keydown', e => { if (e.key === 'Enter') sendMessage(); });

        async function sendMessage() {
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            addMessage('user', text);

            if (currentStream) { currentStream.close(); }

            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text }),
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                addMessage('error', data.error || 'Failed to start chat.');
                return;
            }

            const data = await response.json();
            currentStream = new EventSource(data.stream_url);

            currentStream.addEventListener('message', e => {
                const data = JSON.parse(e.data);
                if (data.kind === 'text') {
                    appendToLast(data.text || '');
                } else if (data.kind === 'error') {
                    addMessage('error', data.error || data.text || '');
                } else if (data.kind === 'tool_dispatch') {
                    addMessage('assistant', 'Running ' + (data.tool?.name || 'tool') + '...');
                } else if (data.kind === 'approval_request') {
                    addMessage('assistant', 'Approval required: ' + (data.approval?.subject || data.text || 'tool call'));
                }
            });

            currentStream.addEventListener('done', () => {
                currentStream.close();
                currentStream = null;
            });

            currentStream.addEventListener('timeout', () => {
                addMessage('assistant', 'Request timed out.');
                currentStream.close();
                currentStream = null;
            });

            currentStream.onerror = () => {
                addMessage('error', 'Connection error.');
                if (currentStream) { currentStream.close(); currentStream = null; }
            };
        }

        function addMessage(role, text) {
            const div = document.createElement('div');
            div.className = 'msg ' + role;
            div.textContent = text;
            messages.appendChild(div);
            messages.scrollTop = messages.scrollHeight;
        }

        function appendToLast(text) {
            const last = messages.lastElementChild;
            if (last && last.classList.contains('assistant')) {
                last.textContent += text;
            } else {
                addMessage('assistant', text);
            }
            messages.scrollTop = messages.scrollHeight;
        }
    </script>
</body>
</html>
"""


async def run_server() -> int:
    import uvicorn

    config = Config.load()
    host = config.serve.host
    port = config.serve.port
    print(f"Axiom server starting at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
    return 0
