"""web_fetch tool tests — SSRF guard and URL validation."""

import asyncio
import json
import os

from reasonix.tool.builtin.web_fetch import WebFetchTool


def test_web_fetch_blocks_loopback_by_default():
    tool = WebFetchTool()

    result = tool._blocked_private_target("http://127.0.0.1:9092/")

    assert result.startswith("Error: private/loopback target is blocked")


def test_web_fetch_blocks_private_and_link_local_addresses():
    tool = WebFetchTool()

    for url in (
        "http://192.168.1.10/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8080/",
        "http://[::1]/",
    ):
        result = tool._blocked_private_target(url)
        assert result.startswith("Error:"), f"expected {url} to be blocked"


def test_web_fetch_allows_public_urls():
    tool = WebFetchTool()

    for url in ("https://example.com/", "https://api.deepseek.com/v1", "http://8.8.8.8/"):
        assert tool._blocked_private_target(url) == "", f"expected {url} to be allowed"


def test_web_fetch_private_block_can_be_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("AXIOM_ALLOW_PRIVATE_WEB_FETCH", "1")
    tool = WebFetchTool()

    assert tool._blocked_private_target("http://127.0.0.1:9092/") == ""
    monkeypatch.delenv("AXIOM_ALLOW_PRIVATE_WEB_FETCH", raising=False)


def test_web_fetch_rejects_non_http_schemes():
    tool = WebFetchTool()

    result = asyncio.run(tool.execute(json.dumps({"url": "file:///etc/passwd"})))

    assert result.startswith("Error: only http:// and https://")


def test_web_fetch_blocks_private_target_through_execute(monkeypatch):
    """The execute path itself must reject private targets, not just the helper."""
    monkeypatch.delenv("AXIOM_ALLOW_PRIVATE_WEB_FETCH", raising=False)
    os.environ.pop("AXIOM_ALLOW_PRIVATE_WEB_FETCH", None)
    tool = WebFetchTool()

    result = asyncio.run(tool.execute(json.dumps({"url": "http://127.0.0.1:9092/"})))

    assert result.startswith("Error: private/loopback target is blocked")
