"""The remote adapter speaks the real OpenCode 1.18 wire contract."""

import json

import httpx
import pytest

from reasonix.event import BufferedSink, Kind
from reasonix.history import SessionStore
from reasonix.remote import OpenCodeClient, RemoteConfig, RemoteError
from reasonix.remote.controller import RemoteController


def test_remote_config_keeps_secrets_out_of_repr():
    config = RemoteConfig("http://127.0.0.1:4096", "/workspace", password="secret")
    assert "secret" not in repr(config)
    with pytest.raises(ValueError):
        RemoteConfig("http://public.example:4096", "/workspace")
    with pytest.raises(ValueError):
        RemoteConfig("http://127.0.0.1:4096", "E:\\project")


async def test_prompt_contract_auth_and_no_automatic_post_retry():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, json={"error": "failed"})

    client = OpenCodeClient(
        RemoteConfig("http://127.0.0.1:4096", "/remote/project", password="secret"),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(RemoteError):
        await client.prompt("ses_123", "run a smoke test")
    assert len(requests) == 1
    assert requests[0].url.path == "/session/ses_123/prompt_async"
    assert requests[0].url.params["directory"] == "/remote/project"
    assert requests[0].headers["authorization"].startswith("Basic ")
    assert json.loads(requests[0].content) == {
        "parts": [{"type": "text", "text": "run a smoke test"}]
    }
    await client.close()


async def test_sse_multiline_data_and_heartbeat():
    def handler(request):
        return httpx.Response(
            200,
            text=(
                ': heartbeat\n\ndata: {"type":\ndata: "server.connected"}\n\n'
                'data: {"type":"message.part.delta","properties":{"delta":"hello"}}\n\n'
            ),
            headers={"Content-Type": "text/event-stream"},
        )

    client = OpenCodeClient(
        RemoteConfig("http://localhost:4096", "/project"),
        transport=httpx.MockTransport(handler),
    )
    events = [event async for event in client.events()]
    assert [event["type"] for event in events] == ["server.connected", "message.part.delta"]
    await client.close()


async def test_remote_file_search_preserves_directory_scope():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=["src/model.py"])

    client = OpenCodeClient(
        RemoteConfig("http://localhost:4096", "/remote/project"),
        transport=httpx.MockTransport(handler),
    )
    assert await client.request(
        "GET",
        "/find/file",
        params={"query": "model", "limit": "40"},
    ) == ["src/model.py"]
    assert seen[0].url.params["directory"] == "/remote/project"
    assert seen[0].url.params["query"] == "model"
    await client.close()


async def test_child_permissions_and_text_deduplication(tmp_path):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=True)

    client = OpenCodeClient(
        RemoteConfig("http://localhost:4096", "/project"),
        transport=httpx.MockTransport(handler),
    )
    sink = BufferedSink()
    controller = RemoteController(client, sink, SessionStore(tmp_path / "state.db"))
    controller.session.id = "parent"
    controller._session_ids = {"parent"}
    await controller.handle_event(
        {
            "type": "session.created",
            "properties": {
                "info": {"id": "child", "parentID": "parent"},
            },
        }
    )
    await controller.handle_event(
        {
            "type": "permission.asked",
            "properties": {
                "id": "permission-1",
                "sessionID": "child",
                "permission": "bash",
                "patterns": ["python train.py"],
            },
        }
    )
    assert controller.pending_approvals[0].id == "permission-1"
    await controller.approve("permission-1", True)
    assert json.loads(requests[0].content) == {"reply": "once"}
    await controller.handle_event(
        {
            "type": "message.part.delta",
            "properties": {
                "sessionID": "parent",
                "partID": "part",
                "field": "text",
                "delta": "hello",
            },
        }
    )
    await controller.handle_event(
        {
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "sessionID": "parent",
                    "id": "part",
                    "type": "text",
                    "text": "hello",
                }
            },
        }
    )
    assert [event.text for event in sink.events if event.kind == Kind.TEXT] == ["hello"]
    await controller.close()
    assert not any(request.url.path.endswith("/abort") for request in requests)
