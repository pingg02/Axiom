"""Phase 1 smoke tests — verify import chain and CLI configuration."""

from reasonix.event import Event, Kind, ToolCallInfo
from reasonix.provider import PROVIDER_FACTORIES, Role
from reasonix.tool.registry import Registry, Tool


def test_event_system():
    """Event types work correctly."""
    e = Event(kind=Kind.TURN_STARTED)
    assert e.kind == Kind.TURN_STARTED
    assert e.text == ""

    e2 = Event(kind=Kind.MESSAGE, text="hello")
    assert e2.text == "hello"

    tc = ToolCallInfo(id="1", name="test", args_json="{}")
    assert tc.name == "test"


def test_tool_registry():
    """Tools can be registered and retrieved."""
    reg = Registry()

    class TestTool(Tool):
        @property
        def name(self) -> str:
            return "test_tool"
        @property
        def description(self) -> str:
            return "A test tool"
        @property
        def schema(self) -> dict:
            return {"type": "object", "properties": {}}

        async def execute(self, args_json: str) -> str:
            return "ok"

    reg.add(TestTool())
    snap = reg.snapshot()
    assert snap.by_name("test_tool") is not None
    assert len(snap.all()) == 1


def test_provider_registry():
    """Provider factories registered and built-in tools available."""
    from reasonix.boot import _default_tools

    reg = _default_tools()
    snap = reg.snapshot()
    assert snap.by_name("bash") is not None
    assert snap.by_name("read_file") is not None

    assert "openai" in PROVIDER_FACTORIES
    assert "anthropic" in PROVIDER_FACTORIES


def test_compose():
    """System prompt composition works."""
    from reasonix.agent.compose import ComposeInput, compose_system_prompt

    reg = Registry()
    snap = reg.snapshot()
    inp = ComposeInput(registry_snapshot=snap)
    prompt = compose_system_prompt(inp)
    assert "You are Reasonix" in prompt


def test_message_roles():
    """Message role enum works."""
    assert Role.SYSTEM == "system"
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.TOOL == "tool"


def test_controller_creation():
    """Controller can be created with noop sink."""
    from reasonix.boot import _default_tools
    from reasonix.control.controller import Controller, ControllerOptions

    class NoopSink:
        def emit(self, event: Event) -> None:
            pass

    reg = _default_tools()
    opts = ControllerOptions(
        registry=reg.snapshot(),
        provider=None,
        sink=NoopSink(),
    )
    ctrl = Controller(opts)
    assert ctrl.session.id != ""
    assert ctrl.session.state.name == "IDLE"
