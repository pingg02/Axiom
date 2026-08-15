"""Desktop bridge tests."""

import asyncio
import json
import os
from dataclasses import dataclass

from reasonix.desktop import (
    BridgeClient,
    WebSocketSink,
    _process_is_alive,
    _search_workspace_entries,
)
from reasonix.event import Event, Kind


def test_websocket_sink():
    """WebSocketSink serializes events into the send queue."""
    sink = WebSocketSink()
    sink.emit(Event(kind=Kind.TEXT, text="hello"))
    sink.emit(Event(kind=Kind.TURN_DONE))
    assert sink.queue.qsize() == 2


def test_bridge_client_import():
    """BridgeClient can be imported."""
    assert BridgeClient is not None


def test_parent_process_probe_detects_current_process():
    assert _process_is_alive(os.getpid())


def test_workspace_search_is_bounded_and_ignores_build_directories(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Composer.tsx").write_text("export {}", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "Composer.js").write_text("", encoding="utf-8")

    results = _search_workspace_entries(tmp_path, "composer")

    assert results == [
        {
            "path": "src/Composer.tsx",
            "name": "Composer.tsx",
            "is_dir": False,
        }
    ]


def test_empty_workspace_search_returns_top_level_entries(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")

    results = _search_workspace_entries(tmp_path, "")

    assert [entry["path"] for entry in results] == ["src", "README.md"]


def test_bridge_client_status_includes_workspace_and_tools(monkeypatch, tmp_path):
    """The desktop frontend can inspect its active workspace and registered tools."""
    import reasonix.desktop as desktop

    @dataclass
    class FakeTool:
        name: str = "read_file"
        description: str = "Read files"
        read_only: bool = True

    class FakeRegistry:
        def all(self):
            return [FakeTool()]

    class FakeSessionState:
        value = "idle"

    class FakeSession:
        id = "session-1"
        state = FakeSessionState()

    class FakeController:
        opts = type(
            "Opts",
            (),
            {
                "registry": FakeRegistry(),
                "configuration_error": "",
                "provider_name": "openai",
                "provider_model": "test-model",
            },
        )()
        session = FakeSession()
        pending_approvals = []
        permission_mode = "ask"

        async def close(self):
            pass

    class FakeWebSocket:
        def __init__(self):
            self.sent = []

        async def send(self, data):
            self.sent.append(data)

    monkeypatch.chdir(tmp_path)

    ws = FakeWebSocket()
    client = desktop.BridgeClient(ws)
    client.controller = FakeController()
    asyncio.run(client.send_status())

    payload = json.loads(ws.sent[-1])
    assert payload["kind"] == "status"
    assert payload["status"]["workspace"] == str(tmp_path)
    assert payload["status"]["tool_count"] == 1
    assert payload["status"]["tools"][0]["name"] == "read_file"
    assert payload["status"]["permission_mode"] == "ask"
    assert payload["status"]["provider"] == {
        "configured": True,
        "name": "openai",
        "model": "test-model",
        "error": "",
    }


def _make_fake_controller():
    """A controller stub just capable of answering send_status()."""

    @dataclass
    class FakeTool:
        name: str = "read_file"
        description: str = "Read files"
        read_only: bool = True

    class FakeRegistry:
        def all(self):
            return [FakeTool()]

    class FakeSessionState:
        value = "idle"

    class FakeSession:
        id = "session-1"
        state = FakeSessionState()

    class FakeController:
        opts = type(
            "Opts",
            (),
            {
                "registry": FakeRegistry(),
                "configuration_error": "",
                "provider_name": "openai",
                "provider_model": "test-model",
            },
        )()
        session = FakeSession()
        pending_approvals = []
        permission_mode = "ask"

        async def close(self):
            pass

    return FakeController()


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, data):
        self.sent.append(data)


def test_bridge_requires_token_before_any_action(monkeypatch):
    """Without a valid auth message, the bridge refuses to drive the agent."""
    import reasonix.desktop as desktop

    async def fake_build(sink=None, history_store=None, **kwargs):
        return _make_fake_controller()

    monkeypatch.setattr(desktop, "build_controller_async", fake_build)
    ws = FakeWebSocket()
    client = desktop.BridgeClient(ws, required_token="launch-secret")
    assert client.controller is None  # controller stays lazy until auth

    # Unauthenticated action is refused and builds no controller.
    asyncio.run(client.handle_message(json.dumps({"action": "send", "text": "hi"})))
    assert json.loads(ws.sent[-1]) == {
        "kind": "error",
        "error": "authentication required",
    }
    assert client.controller is None

    # A wrong token is rejected without building a controller.
    asyncio.run(client.handle_message(json.dumps({"action": "auth", "token": "wrong"})))
    assert json.loads(ws.sent[-1]) == {"kind": "error", "error": "invalid security token"}
    assert client.controller is None


def test_bridge_accepts_valid_token_and_replies_status(monkeypatch):
    """Authenticating with the correct token unlocks the bridge and builds the controller."""
    import reasonix.desktop as desktop

    async def fake_build(sink=None, history_store=None, **kwargs):
        return _make_fake_controller()

    monkeypatch.setattr(desktop, "build_controller_async", fake_build)
    ws = FakeWebSocket()
    client = desktop.BridgeClient(ws, required_token="launch-secret")

    asyncio.run(client.handle_message(json.dumps({"action": "auth", "token": "launch-secret"})))

    payload = json.loads(ws.sent[-1])
    assert payload["kind"] == "status"
    assert client.controller is not None

    # Authenticated actions now go through.
    ws.sent.clear()
    asyncio.run(client.handle_message(json.dumps({"action": "status"})))
    assert json.loads(ws.sent[-1])["kind"] == "status"


def test_bridge_open_when_no_token_configured(monkeypatch):
    """Without a required token (CLI/dev), the bridge stays open for compatibility."""
    import reasonix.desktop as desktop

    async def fake_build(sink=None, history_store=None, **kwargs):
        return _make_fake_controller()

    monkeypatch.setattr(desktop, "build_controller_async", fake_build)
    ws = FakeWebSocket()
    client = desktop.BridgeClient(ws, required_token="")
    assert client._authenticated is True

    asyncio.run(client.handle_message(json.dumps({"action": "status"})))
    assert json.loads(ws.sent[-1])["kind"] == "status"
