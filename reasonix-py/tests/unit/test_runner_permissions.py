import asyncio

from reasonix.agent.runner import Runner, RunnerOptions
from reasonix.control.controller import Controller, ControllerOptions
from reasonix.event import BufferedSink, Kind
from reasonix.memory import MemorySet
from reasonix.permission.permission import Decision, Gate, Policy, Rule
from reasonix.provider import Message, Provider, Role, StreamEvent, ToolCall, Usage
from reasonix.tool.base import Tool
from reasonix.tool.registry import Registry


class ReadOnlyProbeTool(Tool):
    @property
    def name(self) -> str:
        return "read_only_probe"

    @property
    def description(self) -> str:
        return "Probe read-only permission handling."

    @property
    def schema(self) -> dict:
        return {"type": "object", "properties": {}}

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, args_json: str) -> str:
        return "executed"


class WriteProbeTool(ReadOnlyProbeTool):
    @property
    def name(self) -> str:
        return "write_probe"

    @property
    def read_only(self) -> bool:
        return False


class ToolCallingProvider(Provider):
    def __init__(self, tool_name: str = "read_only_probe", args_json: str = "{}") -> None:
        self.tool_name = tool_name
        self.args_json = args_json

    @property
    def model_name(self) -> str:
        return "test-model"

    async def generate(self, messages, tools=None, temperature=0.0, max_tokens=None):
        return Message(role=Role.ASSISTANT), Usage()

    async def generate_stream(self, messages, tools=None, temperature=0.0, max_tokens=None):
        yield StreamEvent(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=[ToolCall(id="call-1", name=self.tool_name, args_json=self.args_json)],
            )
        )
        yield StreamEvent(message=Message(role=Role.ASSISTANT, content="done"))


class MultiToolCallingProvider(ToolCallingProvider):
    async def generate_stream(self, messages, tools=None, temperature=0.0, max_tokens=None):
        yield StreamEvent(
            message=Message(
                role=Role.ASSISTANT,
                tool_calls=[
                    ToolCall(id="call-1", name="write_probe", args_json='{"path":"a"}'),
                    ToolCall(id="call-2", name="write_probe", args_json='{"path":"b"}'),
                ],
            )
        )


def test_runner_passes_tool_read_only_flag_to_permission_gate():
    registry = Registry()
    registry.add(ReadOnlyProbeTool())
    sink = BufferedSink()
    runner = Runner(
        RunnerOptions(
            sink=sink,
            registry=registry.snapshot(),
            provider=ToolCallingProvider(),
            memory=MemorySet(),
            max_steps=1,
            permission_gate=Gate(Policy(mode=Decision.ASK)),
        )
    )

    asyncio.run(runner.run("use the probe"))

    tool_results = [event for event in sink.events if event.kind == Kind.TOOL_RESULT]
    assert tool_results
    assert tool_results[0].tool.output == "executed"


def test_controller_emits_ask_request_and_resumes_after_answer():
    registry = Registry()
    from reasonix.tool.builtin.ask import AskTool
    registry.add(AskTool())
    sink = BufferedSink()
    ask_args = (
        '{"questions":[{"header":"Mode","question":"Choose mode",'
        '"options":[{"label":"Plan"},{"label":"Act"}]}]}'
    )
    controller = Controller(
        ControllerOptions(
            sink=sink,
            registry=registry.snapshot(),
            provider=ToolCallingProvider(tool_name="ask", args_json=ask_args),
            memory=MemorySet(),
            max_steps=1,
            permission_gate=Gate(Policy(mode=Decision.ASK)),
        )
    )

    async def run_turn():
        await controller.send("ask me")
        for _ in range(50):
            asks = [event for event in sink.events if event.kind == Kind.ASK_REQUEST]
            if asks:
                await controller.answer_ask(asks[0].ask_id, ["Plan"])
                break
            await asyncio.sleep(0.01)
        await controller.wait_for_turn()

    asyncio.run(run_turn())

    asks = [event for event in sink.events if event.kind == Kind.ASK_REQUEST]
    assert asks
    assert asks[0].ask_questions[0].question == "Choose mode"
    assert asks[0].ask_questions[0].options == ["Plan", "Act"]
    tool_results = [event for event in sink.events if event.kind == Kind.TOOL_RESULT]
    assert tool_results
    assert '"Plan"' in tool_results[0].tool.output


def test_controller_emits_approval_request_and_resumes_after_approval():
    registry = Registry()
    registry.add(WriteProbeTool())
    sink = BufferedSink()
    controller = Controller(
        ControllerOptions(
            sink=sink,
            registry=registry.snapshot(),
            provider=ToolCallingProvider(tool_name="write_probe"),
            memory=MemorySet(),
            max_steps=1,
            permission_gate=Gate(Policy(mode=Decision.ASK)),
        )
    )

    async def run_turn():
        await controller.send("use the write probe")
        for _ in range(50):
            approvals = [event for event in sink.events if event.kind == Kind.APPROVAL_REQUEST]
            if approvals:
                await controller.approve(approvals[0].approval.id, True)
                break
            await asyncio.sleep(0.01)
        await controller.wait_for_turn()

    asyncio.run(run_turn())

    approvals = [event for event in sink.events if event.kind == Kind.APPROVAL_REQUEST]
    assert approvals
    assert approvals[0].approval.tool_name == "write_probe"
    tool_results = [event for event in sink.events if event.kind == Kind.TOOL_RESULT]
    assert tool_results
    assert tool_results[0].tool.output == "executed"


def test_controller_queues_and_approves_a_whole_tool_batch_for_session():
    registry = Registry()
    registry.add(WriteProbeTool())
    sink = BufferedSink()
    policy = Policy(mode=Decision.ASK)
    controller = Controller(
        ControllerOptions(
            sink=sink,
            registry=registry.snapshot(),
            provider=MultiToolCallingProvider(),
            memory=MemorySet(),
            max_steps=1,
            permission_gate=Gate(policy),
        )
    )

    async def run_turn():
        await controller.send("write both files")
        for _ in range(100):
            approvals = [
                event for event in sink.events
                if event.kind == Kind.APPROVAL_REQUEST
            ]
            if len(approvals) == 2:
                assert len(controller.pending_approvals) == 2
                assert await controller.approve_all(True, "session") == 2
                break
            await asyncio.sleep(0.01)
        await controller.wait_for_turn()

    asyncio.run(run_turn())

    approvals = [event for event in sink.events if event.kind == Kind.APPROVAL_REQUEST]
    tool_results = [event for event in sink.events if event.kind == Kind.TOOL_RESULT]
    assert len(approvals) == 2
    assert len(tool_results) == 2
    assert not controller.pending_approvals
    assert policy.session_allow


def test_controller_permission_posture_is_scoped_to_one_session():
    registry = Registry()
    policy = Policy(mode=Decision.ASK)
    controller = Controller(
        ControllerOptions(
            registry=registry.snapshot(),
            permission_gate=Gate(policy),
        )
    )

    assert controller.permission_mode == "ask"
    assert controller.set_permission_mode("allow") == "allow"
    policy.session_allow.append(Rule(tool_name="write_probe"))
    assert controller.permission_mode == "allow"

    asyncio.run(controller.new_session())

    assert controller.permission_mode == "ask"
    assert policy.session_allow == []
