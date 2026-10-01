"""OpenCode 1.18 HTTP contract; secrets remain in memory."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx


class RemoteError(RuntimeError):
    """A remote transport or API error safe to show in the desktop UI."""


@dataclass(frozen=True)
class RemoteConfig:
    url: str
    directory: str
    username: str = "opencode"
    password: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("OpenCode URL must use http:// or https://")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Keep credentials and query parameters out of the server URL")
        if not self.directory.startswith("/") or "\x00" in self.directory:
            raise ValueError("Use the absolute Linux project directory on the remote server")
        if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Use HTTPS, or connect through a loopback SSH tunnel")


class OpenCodeClient:
    def __init__(
        self, config: RemoteConfig, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.config = config
        self.http = httpx.AsyncClient(
            base_url=config.url.rstrip("/") + "/",
            params={"directory": config.directory},
            auth=httpx.BasicAuth(config.username, config.password) if config.password else None,
            timeout=httpx.Timeout(30, read=300),
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        params: dict[str, str] | None = None,
    ) -> Any:
        try:
            response = await self.http.request(
                method,
                path.lstrip("/"),
                json=body,
                params=params,
            )
            response.raise_for_status()
            return response.json() if response.content else None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise RemoteError("Remote OpenCode rejected authentication or permission") from exc
            raise RemoteError(f"Remote OpenCode returned HTTP {status}") from exc
        except (httpx.RequestError, ValueError) as exc:
            raise RemoteError(f"Remote OpenCode connection failed ({type(exc).__name__})") from exc

    async def health(self) -> dict[str, Any]:
        result = await self.request("GET", "/global/health")
        if not isinstance(result, dict) or result.get("healthy") is not True:
            raise RemoteError("The endpoint is not a healthy OpenCode server")
        return result

    async def create_session(self) -> dict[str, Any]:
        result = await self.request("POST", "/session", {"permission": self.permissions("ask")})
        if not isinstance(result, dict) or not result.get("id"):
            raise RemoteError("Invalid OpenCode session response")
        return result

    @staticmethod
    def permissions(mode: str) -> list[dict[str, str]]:
        if mode not in {"ask", "allow", "deny"}:
            raise ValueError("Invalid permission mode")
        return [{"permission": "*", "pattern": "*", "action": mode}]

    @staticmethod
    def session_path(session_id: str, suffix: str = "") -> str:
        return f"/session/{quote(session_id, safe='')}{suffix}"

    async def prompt(self, session_id: str, text: str) -> None:
        # Never retry this POST automatically: acknowledgement may have been lost
        # after the remote server already started the model or a training job.
        await self.request(
            "POST",
            self.session_path(session_id, "/prompt_async"),
            {"parts": [{"type": "text", "text": text}]},
        )

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        try:
            async with self.http.stream("GET", "event") as response:
                response.raise_for_status()
                data: list[str] = []
                size = 0
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        value = line[5:].lstrip(" ")
                        size += len(value)
                        if size > 2 * 1024 * 1024:
                            raise RemoteError("Remote event exceeded the size limit")
                        data.append(value)
                    elif not line and data:
                        payload = json.loads("\n".join(data))
                        if isinstance(payload, dict):
                            yield payload
                        data = []
                        size = 0
        except httpx.HTTPStatusError as exc:
            raise RemoteError(
                f"Remote event stream returned HTTP {exc.response.status_code}"
            ) from exc
        except (httpx.RequestError, ValueError) as exc:
            raise RemoteError(f"Remote event stream disconnected ({type(exc).__name__})") from exc
