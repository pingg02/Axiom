"""Load LangChain MCP tools into the Axiom/Reasonix tool registry."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, cast

from langchain_mcp_adapters import client as mcp_client
from langchain_mcp_adapters.sessions import Connection

from reasonix.tool.base import Tool
from reasonix.tool.registry import Registry

logger = logging.getLogger(__name__)


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return normalized or "tool"


def _schema_from_tool(tool: Any) -> dict[str, Any]:
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, dict):
        return cast(dict[str, Any], schema)
    if schema is not None and hasattr(schema, "model_json_schema"):
        return cast(dict[str, Any], schema.model_json_schema())
    if schema is not None and hasattr(schema, "schema"):
        return cast(dict[str, Any], schema.schema())
    return {"type": "object", "properties": {}}


@dataclass
class MCPServerStatus:
    name: str
    transport: str
    state: str
    tool_count: int = 0
    error: str = ""


class MCPToolWrapper(Tool):
    """Adapt a LangChain MCP StructuredTool to the local Tool interface."""

    def __init__(self, mcp_tool: Any, server_name: str) -> None:
        self._mcp_tool = mcp_tool
        self._server_name = server_name
        self._name = f"{_safe_name(server_name)}_{_safe_name(str(mcp_tool.name))}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        description = str(getattr(self._mcp_tool, "description", "") or "")
        return f"[MCP · {self._server_name}] {description}".strip()

    @property
    def schema(self) -> dict[str, Any]:
        return _schema_from_tool(self._mcp_tool)

    @property
    def read_only(self) -> bool:
        # MCP does not define a universally trustworthy read-only flag.
        return False

    async def execute(self, args_json: str) -> str:
        args = json.loads(args_json or "{}")
        result = await self._mcp_tool.ainvoke(args)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)


async def register_mcp_tools(
    registry: Registry,
    servers: dict[str, dict[str, Any]],
) -> tuple[Any | None, list[MCPServerStatus]]:
    """Connect configured MCP servers and register their discovered tools."""
    if not servers:
        return None, []

    normalized: dict[str, Connection] = {}
    statuses: list[MCPServerStatus] = []
    for name, raw in servers.items():
        config = dict(raw)
        transport = str(config.get("transport") or ("stdio" if config.get("command") else "http"))
        config["transport"] = transport
        normalized[name] = cast(Connection, config)
        statuses.append(MCPServerStatus(name=name, transport=transport, state="connecting"))

    client = mcp_client.MultiServerMCPClient(normalized)
    try:
        tools = await client.get_tools()
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("Failed to discover MCP tools")
        for status in statuses:
            status.state = "error"
            status.error = error
        return client, statuses

    counts = {name: 0 for name in normalized}
    for tool in tools:
        metadata = getattr(tool, "metadata", {}) or {}
        server_name = str(metadata.get("server_name") or metadata.get("server") or "mcp")
        if server_name not in normalized and len(normalized) == 1:
            server_name = next(iter(normalized))
        wrapper = MCPToolWrapper(tool, server_name)
        try:
            registry.add(wrapper)
            if server_name in counts:
                counts[server_name] += 1
        except ValueError:
            logger.warning("Skipping duplicate MCP tool name: %s", wrapper.name)

    for status in statuses:
        status.state = "connected"
        status.tool_count = counts.get(status.name, 0)
    return client, statuses
