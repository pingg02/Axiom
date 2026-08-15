"""Built-in tool: web_fetch — fetch URL and return text content."""

import ipaddress
import json
import os
import socket
import urllib.parse
from typing import Any

import httpx

from reasonix import __version__
from reasonix.tool.base import Tool


class WebFetchTool(Tool):
    """Fetch a URL and return its text content."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch a URL and return the raw response body (HTML, JSON, or text)."

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute URL beginning with http:// or https://"},
            },
            "required": ["url"],
        }

    @property
    def read_only(self) -> bool:
        return True

    @staticmethod
    def _blocked_private_target(url: str) -> str:
        """Reject loopback/private/link-local targets unless explicitly allowed.

        The agent can be prompt-injected into fetching local services (its own
        WebSocket bridge, the Java security port, cloud metadata endpoints),
        so private targets fail closed by default. Set
        AXIOM_ALLOW_PRIVATE_WEB_FETCH=1 to allow them explicitly.
        """
        if os.environ.get("AXIOM_ALLOW_PRIVATE_WEB_FETCH", "").lower() in {"1", "true", "yes"}:
            return ""
        hostname = urllib.parse.urlparse(url).hostname
        if not hostname:
            return ""
        if hostname.lower() in {"localhost", "localhost.localdomain"}:
            return f"Error: loopback target is blocked by default: {hostname}"
        try:
            infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return ""
        for info in infos:
            try:
                address = ipaddress.ip_address(info[4][0])
            except ValueError:
                continue
            if (
                address.is_loopback
                or address.is_private
                or address.is_link_local
                or address.is_reserved
                or address.is_multicast
            ):
                return f"Error: private/loopback target is blocked by default: {hostname}"
        return ""

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        url = args["url"]
        if not url.startswith(("http://", "https://")):
            return f"Error: only http:// and https:// URLs are supported, got: {url[:50]}"
        blocked = self._blocked_private_target(url)
        if blocked:
            return blocked
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                headers = {
                    "User-Agent": f"Axiom/{__version__} (Reasonix-compatible)"
                }
                async with client.stream("GET", url, headers=headers) as resp:
                    resp.raise_for_status()
                    chunks = []
                    total = 0
                    async for chunk in resp.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > 500_000:
                            chunks.append(b"\n...(truncated at 500KB)")
                            break
                    text = b"".join(chunks).decode("utf-8", errors="replace")
                return text
        except httpx.TimeoutException:
            return f"Request timed out: {url}"
        except httpx.HTTPStatusError as e:
            return f"HTTP {e.response.status_code}: {url}"
        except Exception as e:
            return f"Error fetching {url}: {e}"
