import asyncio

from langchain_mcp_adapters import client as mcp_client

from reasonix.tool.mcp_loader import MCPToolWrapper, register_mcp_tools
from reasonix.tool.registry import Registry


class FakeStructuredTool:
    name = "read-file"
    description = "Read a file from the connected service."
    args_schema = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }
    metadata = {"server_name": "files"}

    async def ainvoke(self, args):
        return {"path": args["path"], "content": "ok"}


def test_mcp_wrapper_uses_namespaced_name_and_requires_approval():
    wrapper = MCPToolWrapper(FakeStructuredTool(), "files")

    assert wrapper.name == "files_read-file"
    assert wrapper.read_only is False
    assert "[MCP · files]" in wrapper.description
    assert wrapper.schema["required"] == ["path"]
    assert '"content": "ok"' in asyncio.run(wrapper.execute('{"path":"README.md"}'))


def test_register_mcp_tools_uses_current_multi_server_client(monkeypatch):
    class FakeClient:
        def __init__(self, connections):
            self.connections = connections

        async def get_tools(self):
            return [FakeStructuredTool()]

    monkeypatch.setattr(mcp_client, "MultiServerMCPClient", FakeClient)
    registry = Registry()

    client, statuses = asyncio.run(
        register_mcp_tools(
            registry,
            {"files": {"transport": "stdio", "command": "fake-mcp"}},
        )
    )

    assert client.connections["files"]["command"] == "fake-mcp"
    assert registry.snapshot().by_name("files_read-file") is not None
    assert statuses[0].state == "connected"
    assert statuses[0].tool_count == 1
