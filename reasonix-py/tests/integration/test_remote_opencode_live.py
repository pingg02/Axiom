"""Opt-in wire smoke test against a real OpenCode, without a paid model call."""

import asyncio
import os

import pytest

from reasonix.remote import OpenCodeClient, RemoteConfig


@pytest.mark.skipif(not os.environ.get("AXIOM_TEST_OPENCODE_URL"), reason="opt-in live server test")
async def test_real_health_sessions_history_and_events():
    client = OpenCodeClient(
        RemoteConfig(
            os.environ["AXIOM_TEST_OPENCODE_URL"],
            os.environ.get("AXIOM_TEST_OPENCODE_DIRECTORY", "/project"),
            password=os.environ.get("AXIOM_TEST_OPENCODE_PASSWORD", ""),
        )
    )
    session_id = ""
    try:
        health = await client.health()
        assert health["healthy"]
        session = await client.create_session()
        session_id = session["id"]
        info = await client.request("GET", client.session_path(session_id))
        assert info["id"] == session_id
        assert await client.request("GET", client.session_path(session_id, "/message")) == []
        assert isinstance(await client.request("GET", "/permission"), list)
        assert isinstance(await client.request("GET", "/question"), list)
        stream = client.events()
        event = await asyncio.wait_for(anext(stream), 15)
        assert event["type"] == "server.connected"
        await stream.aclose()
    finally:
        if session_id:
            await client.request("DELETE", client.session_path(session_id))
        await client.close()
