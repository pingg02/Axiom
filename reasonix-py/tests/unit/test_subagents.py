import json

from reasonix.control.controller import Controller, ControllerOptions
from reasonix.event import BufferedSink, Kind
from reasonix.history import SessionStore
from reasonix.permission.permission import Decision, Gate, Policy, Rule
from reasonix.provider import Message, Role, StreamEvent, ToolCall
from reasonix.tool.builtin.bash import BashTool
from reasonix.tool.builtin.task import TaskTool
from reasonix.tool.registry import Registry


class TaskProvider:
    model_name = "test"

    def __init__(self, recursive=False):
        self.calls = []
        self.recursive = recursive

    async def generate_stream(self, messages, tools=None, temperature=0):
        self.calls.append((list(messages), tools))
        prompt = next(
            message.content for message in reversed(messages) if message.role == Role.USER
        )
        has_result = any(message.role == Role.TOOL for message in messages)
        has_task = any(tool["function"]["name"] == "task" for tool in (tools or []))
        if not has_result and has_task and (prompt == "parent" or self.recursive):
            yield StreamEvent(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(
                            id=f"task-{len(self.calls)}",
                            name="task",
                            args_json=json.dumps({"prompt": "child", "description": "inspect"}),
                        ),
                    ],
                )
            )
            return
        yield StreamEvent(message=Message(role=Role.ASSISTANT, content=f"answer:{prompt}"))


def controller(tmp_path, provider, **options):
    registry = Registry()
    registry.add(TaskTool())
    return Controller(
        ControllerOptions(
            registry=registry.snapshot(),
            provider=provider,
            sink=BufferedSink(),
            history_store=SessionStore(tmp_path / "state.db"),
            workspace=str(tmp_path),
            **options,
        )
    )


async def test_real_subagent_isolated_history_persisted_and_parent_continues(tmp_path):
    provider = TaskProvider()
    owner = controller(tmp_path, provider)
    await owner.send("parent")
    await owner.wait_for_turn()
    assert not owner.last_error
    assert len(provider.calls) == 3
    assert [m.content for m in provider.calls[1][0] if m.role == Role.USER] == ["child"]
    assert "answer:child" in owner.history_messages[-2].content
    store = owner.opts.history_store
    runs = store.subagent_runs(owner.session.id)
    assert len(runs) == 1
    child_id = runs[0]["child_id"]
    assert store.load_messages(child_id)[-1].content == "answer:child"
    assert store.get_session(child_id).status == "idle"
    events = owner.opts.sink.events
    assert sum(event.kind == Kind.TURN_DONE for event in events) == 1


async def test_shared_budget_caps_parent_and_children(tmp_path):
    provider = TaskProvider()
    owner = controller(tmp_path, provider, max_steps=2)
    await owner.send("parent")
    await owner.wait_for_turn()
    assert len(provider.calls) == 2
    assert "budget exhausted" in owner.last_error


async def test_depth_limit_removes_task_and_tracks_actual_parent(tmp_path):
    provider = TaskProvider(recursive=True)
    owner = controller(tmp_path, provider)
    await owner.send("parent")
    await owner.wait_for_turn()
    store = owner.opts.history_store
    children = store.subagent_runs(owner.session.id)
    assert len(children) == 1
    grandchildren = store.subagent_runs(children[0]["child_id"])
    assert grandchildren[0]["depth"] == 2
    deepest_tools = provider.calls[2][1]
    assert all(tool["function"]["name"] != "task" for tool in (deepest_tools or []))


async def test_standalone_task_never_claims_fake_success():
    assert (await TaskTool().execute('{"prompt":"test"}')).startswith("Error:")


class ChildBashProvider(TaskProvider):
    async def generate_stream(self, messages, tools=None, temperature=0):
        prompt = next(
            message.content for message in reversed(messages) if message.role == Role.USER
        )
        if prompt == "child" and not any(message.role == Role.TOOL for message in messages):
            yield StreamEvent(
                message=Message(
                    role=Role.ASSISTANT,
                    tool_calls=[
                        ToolCall(id="bash-1", name="bash", args_json='{"command":"echo guarded"}'),
                    ],
                )
            )
            return
        async for event in super().generate_stream(messages, tools, temperature):
            yield event


async def test_subagent_inherits_deny_policy_and_fail_closed_java_boundary(tmp_path):
    for deny in (True, False):
        registry = Registry()
        registry.add(TaskTool())
        registry.add(BashTool())
        sink = BufferedSink()
        owner = Controller(
            ControllerOptions(
                registry=registry.snapshot(),
                provider=ChildBashProvider(),
                sink=sink,
                workspace=str(tmp_path),
                security_required=True,
                permission_gate=Gate(
                    Policy(
                        mode=Decision.ALLOW,
                        deny=[Rule(tool_name="bash")] if deny else [],
                    )
                ),
            )
        )
        await owner.send("parent")
        await owner.wait_for_turn()
        result = next(
            event
            for event in sink.events
            if event.kind == Kind.TOOL_RESULT and event.tool.name == "bash"
        )
        assert (
            "Permission denied" if deny else "Java security service is unavailable"
        ) in result.tool.error
        assert not result.tool.output
