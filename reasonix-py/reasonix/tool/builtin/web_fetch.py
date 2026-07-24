"""Built-in tool: web_fetch — fetch URL and return text content."""

import json
from typing import Any

import httpx

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

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json)
        url = args["url"]
        if not url.startswith(("http://", "https://")):
            return f"Error: only http:// and https:// URLs are supported, got: {url[:50]}"
        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                headers = {"User-Agent": "Axiom/0.2 (Reasonix-compatible)"}
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
