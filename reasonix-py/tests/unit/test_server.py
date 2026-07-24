"""FastAPI server tests."""

from fastapi.testclient import TestClient

from reasonix.event import Event, Kind
from reasonix.serve.server import CHAT_HTML, SSESink, app


def test_app_created():
    """FastAPI app can be created."""
    assert app.title == "Axiom"


def test_index_route():
    """Core routes exist."""
    routes = [r.path for r in app.routes]
    assert "/" in routes
    assert "/chat" in routes
    assert "/stream/{session_id}" in routes


def test_sse_sink():
    """SSESink can enqueue emitted events."""
    sink = SSESink()
    sink.emit(Event(kind=Kind.TEXT, text="hello"))
    sink.emit(Event(kind=Kind.TURN_DONE))

    assert sink.queue.qsize() == 2


def test_chat_post_creates_stream_that_does_not_require_message_query(monkeypatch):
    """POST /chat should bind the message to a session and return a usable SSE URL."""
    import reasonix.serve.server as server

    class FakeController:
        async def send(self, message):
            assert message == "hello from web"
            self._sink.emit(Event(kind=Kind.TEXT, text="pong"))
            self._sink.emit(Event(kind=Kind.TURN_DONE))

        async def wait_for_turn(self):
            return None

        async def close(self):
            return None

    def fake_build_controller(sink):
        ctrl = FakeController()
        ctrl._sink = sink
        return ctrl

    monkeypatch.setattr(server, "build_controller", fake_build_controller)
    server.manager.clear()

    client = TestClient(app)
    response = client.post("/chat", json={"message": "hello from web"})
    assert response.status_code == 200
    stream_url = response.json()["stream_url"]

    with client.stream("GET", stream_url) as stream_response:
        assert stream_response.status_code == 200
        body = "".join(stream_response.iter_text())

    assert "pong" in body
    assert "message query param required" not in body


def test_index_html_uses_chat_session_stream_url():
    """The built-in web client should use the POST /chat stream_url contract."""
    assert "fetch('/chat'" in CHAT_HTML
    assert "/stream/chat?message=" not in CHAT_HTML
