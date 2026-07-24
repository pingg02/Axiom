"""Shared frontend event-contract tests."""

from reasonix.event import (
    ApprovalRequest,
    AskQuestion,
    Event,
    Kind,
    ToolCallInfo,
    UsageInfo,
)


def test_event_to_frontend_dict_includes_interactive_fields():
    """All frontends should receive the same approval, ask, tool, and usage shape."""
    import reasonix.event as event_mod

    assert hasattr(event_mod, "event_to_frontend_dict")

    event = Event(
        kind=Kind.APPROVAL_REQUEST,
        text="Need approval",
        tool=ToolCallInfo(
            id="tool-1",
            name="write_file",
            args_json='{"path":"x.txt"}',
            read_only=False,
        ),
        usage=UsageInfo(input_tokens=3, output_tokens=5, cost_usd=0.01),
        approval=ApprovalRequest(
            id="approval-1",
            tool_name="write_file",
            subject="x.txt",
            args_json='{"path":"x.txt"}',
        ),
        ask_id="ask-1",
        ask_questions=[
            AskQuestion(
                header="Mode",
                question="Choose mode",
                options=["Plan", "Act"],
                multi_select=False,
            )
        ],
    )

    data = event_mod.event_to_frontend_dict(event)

    assert data["kind"] == "approval_request"
    assert data["tool"]["args_json"] == '{"path":"x.txt"}'
    assert data["tool"]["read_only"] is False
    assert data["usage"]["cost_usd"] == 0.01
    assert data["approval"]["id"] == "approval-1"
    assert data["approval"]["subject"] == "x.txt"
    assert data["ask_id"] == "ask-1"
    assert data["ask_questions"][0]["options"] == ["Plan", "Act"]
