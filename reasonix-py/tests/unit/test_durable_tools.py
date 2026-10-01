import json

from reasonix.control.controller import Controller, ControllerOptions
from reasonix.event import BufferedSink
from reasonix.history import SessionStore
from reasonix.provider import Message, Role, StreamEvent, ToolCall
from reasonix.tool.base import Tool
from reasonix.tool.registry import Registry


class WriteOnce(Tool):
    name = "write_once"
    description = "Write a test file"
    schema = {"type": "object"}

    def __init__(self, path):
        self.path = path
        self.calls = 0

    async def execute(self, args_json):
        self.calls += 1
        self.path.write_text("written")
        return "written"


class InterruptedProvider:
    model_name = "test"

    def __init__(self):
        self.calls = 0

    async def generate_stream(self, messages, tools=None, temperature=0):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("connection lost after tool result")
        yield StreamEvent(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=[
                    ToolCall(id="write-1", name="write_once", args_json="{}"),
                ],
            )
        )


async def test_crash_after_tool_preserves_result_without_reexecuting(tmp_path):
    store = SessionStore(tmp_path / "state.db")
    tool = WriteOnce(tmp_path / "result.txt")
    registry = Registry()
    registry.add(tool)
    controller = Controller(
        ControllerOptions(
            registry=registry.snapshot(),
            provider=InterruptedProvider(),
            history_store=store,
            sink=BufferedSink(),
            workspace=str(tmp_path),
        )
    )
    await controller.send("write it")
    await controller.wait_for_turn()
    messages = store.load_messages(controller.session.id)
    assert messages[-1].role == Role.TOOL
    assert messages[-1].content == "written"
    assert store.tool_executions(controller.session.id)[0]["state"] == "completed"
    resumed = Controller(controller.opts)
    await resumed.resume_session(controller.session.id)
    assert tool.calls == 1
    assert resumed.history_messages[-1].content == "written"
    assert resumed.recovery_prompt == "write it"


def test_unknown_tool_outcome_is_closed_without_replay(tmp_path):
    store = SessionStore(tmp_path / "state.db")
    store.create_session("s", title="test", workspace=str(tmp_path), created_at=1)
    call = ToolCall(id="c", name="bash", args_json=json.dumps({"command": "train"}))
    store.save_messages("s", [Message(role=Role.ASSISTANT, tool_calls=[call])])
    store.record_tool("s", "turn", call, "running", "")
    history = store.reconcile_interrupted_tools("s")
    assert history[-1].role == Role.TOOL
    assert "outcome is unknown" in history[-1].content
    assert "Do not automatically retry" in history[-1].content
    assert len(store.reconcile_interrupted_tools("s")) == 2
