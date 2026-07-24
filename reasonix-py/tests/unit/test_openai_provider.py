import asyncio
import json

from langchain_core.messages import AIMessage, AIMessageChunk

from reasonix.provider import Message, Role, ToolCall
from reasonix.provider.openai import OpenAIProvider, _from_lc_msg, _to_lc_msg


def test_from_lc_msg_accepts_langchain_tool_call_shape():
    msg = AIMessage(
        content="",
        tool_calls=[{"id": "call-1", "name": "read_file", "args": {"path": "README.md"}}],
    )

    converted = _from_lc_msg(msg)

    assert converted.role == Role.ASSISTANT
    assert len(converted.tool_calls) == 1
    assert converted.tool_calls[0].id == "call-1"
    assert converted.tool_calls[0].name == "read_file"
    assert json.loads(converted.tool_calls[0].args_json) == {"path": "README.md"}


def test_to_lc_msg_emits_langchain_tool_call_shape():
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="call-1", name="read_file", args_json='{"path": "README.md"}')],
    )

    converted = _to_lc_msg(msg)

    assert converted.tool_calls
    assert converted.tool_calls[0]["id"] == "call-1"
    assert converted.tool_calls[0]["name"] == "read_file"
    assert converted.tool_calls[0]["args"] == {"path": "README.md"}


def test_to_lc_msg_preserves_invalid_tool_args_as_raw_string():
    msg = Message(
        role=Role.ASSISTANT,
        content="",
        tool_calls=[ToolCall(id="call-1", name="bash", args_json="{bad json")],
    )

    converted = _to_lc_msg(msg)

    assert json.dumps(converted.tool_calls[0]["args"])


def test_generate_stream_merges_incremental_tool_call_chunks_by_index():
    """Streaming tool-call chunks without repeated id/name should merge into one valid call."""

    class FakeStreamingLLM:
        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"id": "call-1", "name": "glob", "args": "", "index": 0}
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"id": None, "name": None, "args": '{"pattern":"*.py"', "index": 0}
                ],
            )
            yield AIMessageChunk(
                content="",
                tool_call_chunks=[
                    {"id": None, "name": None, "args": '}', "index": 0}
                ],
            )

    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._model_name = "fake"
    provider._llm = FakeStreamingLLM()

    async def collect_final_message():
        final = None
        async for event in provider.generate_stream(
            messages=[Message(role=Role.USER, content="find python files")],
            tools=[{"function": {"name": "glob", "description": "", "parameters": {}}}],
        ):
            if event.message:
                final = event.message
        return final

    final_message = asyncio.run(collect_final_message())

    assert final_message is not None
    assert final_message.tool_calls == [
        ToolCall(id="call-1", name="glob", args_json='{"pattern":"*.py"}')
    ]
