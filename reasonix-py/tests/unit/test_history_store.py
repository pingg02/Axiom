import asyncio

from reasonix.control.controller import Controller, ControllerOptions
from reasonix.diff import build_change
from reasonix.event import BufferedSink
from reasonix.history import SessionStore
from reasonix.provider import Message, Role, StreamEvent, ToolCall
from reasonix.tool.registry import Registry


class CapturingProvider:
    model_name = "capture-model"

    def __init__(self):
        self.calls = []

    async def generate_stream(self, messages, tools=None, temperature=0.0):
        self.calls.append(list(messages))
        yield StreamEvent(
            message=Message(
                role=Role.ASSISTANT,
                content=f"reply-{len(self.calls)}",
            )
        )


def test_session_store_round_trips_messages_and_marks_crash_checkpoint(tmp_path):
    path = tmp_path / "state" / "axiom.db"
    store = SessionStore(path)
    store.create_session(
        "session-1",
        title="Test",
        workspace=str(tmp_path),
        created_at=10.0,
    )
    messages = [
        Message(role=Role.USER, content="hello"),
        Message(
            role=Role.ASSISTANT,
            tool_calls=[ToolCall(id="tool-1", name="read_file", args_json="{}")],
        ),
        Message(
            role=Role.TOOL,
            name="read_file",
            tool_call_id="tool-1",
            content="content",
        ),
    ]
    store.save_messages("session-1", messages)
    store.save_checkpoint("session-1", "continue this", messages)

    reopened = SessionStore(path)

    assert reopened.get_session("session-1").status == "interrupted"
    assert reopened.checkpoint_prompt("session-1") == "continue this"
    loaded = reopened.load_messages("session-1")
    assert [message.role for message in loaded] == [
        Role.USER,
        Role.ASSISTANT,
        Role.TOOL,
    ]
    assert loaded[1].tool_calls[0].name == "read_file"


def test_controller_reuses_and_persists_prior_turn_context(tmp_path):
    store = SessionStore(tmp_path / "axiom.db")
    provider = CapturingProvider()
    controller = Controller(
        ControllerOptions(
            registry=Registry().snapshot(),
            provider=provider,
            sink=BufferedSink(),
            history_store=store,
            workspace=str(tmp_path),
        )
    )

    async def run_two_turns():
        await controller.send("first question")
        await controller.wait_for_turn()
        await controller.send("second question")
        await controller.wait_for_turn()

    asyncio.run(run_two_turns())

    assert len(provider.calls) == 2
    assert [message.content for message in provider.calls[1] if message.role != Role.SYSTEM] == [
        "first question",
        "reply-1",
        "second question",
    ]
    stored = store.load_messages(controller.session.id)
    assert [message.content for message in stored] == [
        "first question",
        "reply-1",
        "second question",
        "reply-2",
    ]
    assert controller.recovery_prompt == ""


def test_controller_undoes_latest_turn_and_refuses_to_overwrite_later_edits(tmp_path):
    store = SessionStore(tmp_path / "axiom.db")
    controller = Controller(
        ControllerOptions(
            registry=Registry().snapshot(),
            provider=CapturingProvider(),
            sink=BufferedSink(),
            history_store=store,
            workspace=str(tmp_path),
        )
    )
    target = tmp_path / "example.txt"
    target.write_text("after\n", encoding="utf-8")
    store.record_change(
        controller.session.id,
        "turn-1",
        build_change(str(target), "before\n", "after\n", "Edit example"),
    )

    assert asyncio.run(controller.undo_last_turn()) == 1
    assert target.read_text(encoding="utf-8") == "before\n"
    assert controller.latest_changes == []

    target.write_text("tool output\n", encoding="utf-8")
    store.record_change(
        controller.session.id,
        "turn-2",
        build_change(str(target), "before\n", "tool output\n", "Edit again"),
    )
    target.write_text("manual edit\n", encoding="utf-8")

    try:
        asyncio.run(controller.undo_last_turn())
    except ValueError as exc:
        assert "changed afterwards" in str(exc)
    else:
        raise AssertionError("Undo should protect later manual edits")
    assert target.read_text(encoding="utf-8") == "manual edit\n"


def test_workflows_are_scoped_to_workspace_and_persisted(tmp_path):
    store = SessionStore(tmp_path / "axiom.db")
    store.save_workflow(
        "workflow-1",
        workspace="E:/project-a",
        name="Release check",
        steps=["Run tests", "Review packaging"],
    )
    store.save_workflow(
        "workflow-2",
        workspace="E:/project-b",
        name="Other project",
        steps=["Do not leak"],
    )

    reopened = SessionStore(tmp_path / "axiom.db")
    workflows = reopened.list_workflows("E:/project-a")

    assert [(item.id, item.name, item.steps) for item in workflows] == [
        ("workflow-1", "Release check", ["Run tests", "Review packaging"])
    ]
    assert reopened.delete_workflow("workflow-1", "E:/project-b") is False
    assert reopened.delete_workflow("workflow-1", "E:/project-a") is True
