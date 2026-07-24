"""Core model/tool execution loop."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from reasonix.agent.compose import ComposeInput, compose_system_prompt
from reasonix.diff import Change
from reasonix.event import AskQuestion, Event, Kind, Sink, ToolCallInfo, UsageInfo
from reasonix.memory import MemorySet
from reasonix.permission.permission import Gate
from reasonix.provider import Message, Provider, Role, StreamEvent, ToolCall
from reasonix.tool.registry import RegistrySnapshot

AskCallback = Callable[[list[AskQuestion]], Awaitable[list[str]]]
ChangeCallback = Callable[[str, Change], None]


@dataclass
class RunnerOptions:
    sink: Sink
    registry: RegistrySnapshot
    provider: Provider
    memory: MemorySet | None = None
    instructions: str = ""
    additional_prompt: str = ""
    language: str = ""
    plan_mode: bool = False
    max_steps: int = 50
    temperature: float = 0.0
    ask_callback: AskCallback | None = None
    permission_gate: Gate | None = None
    history: list[Message] = field(default_factory=list)
    change_callback: ChangeCallback | None = None


@dataclass
class TurnResult:
    success: bool = True
    error: str = ""
    message: Message | None = None
    usage: UsageInfo | None = None
    steps: int = 0
    messages: list[Message] = field(default_factory=list)


class Runner:
    """Execute one user turn and discard after completion."""

    def __init__(self, opts: RunnerOptions) -> None:
        self.opts = opts

    async def run(self, user_input: str) -> TurnResult:
        sink = self.opts.sink
        sink.emit(Event(kind=Kind.TURN_STARTED))

        system_text = compose_system_prompt(
            ComposeInput(
                registry_snapshot=self.opts.registry,
                memory=self.opts.memory,
                instructions=self.opts.instructions,
                additional_prompt=self.opts.additional_prompt,
                language=self.opts.language,
                plan_mode=self.opts.plan_mode,
            )
        )
        conversation = [
            Message(role=Role.SYSTEM, content=system_text),
            *self.opts.history,
            Message(role=Role.USER, content=user_input),
        ]
        total_usage = UsageInfo()
        final_message: Message | None = None
        error = ""
        steps = 0

        while steps < self.opts.max_steps:
            steps += 1
            assistant, usage = await self._call_llm(
                sink,
                conversation,
                self.opts.registry.to_openai_tools(),
            )
            if usage:
                total_usage.input_tokens += usage.input_tokens
                total_usage.output_tokens += usage.output_tokens
                total_usage.cache_read_tokens += usage.cache_read_tokens
                total_usage.cache_write_tokens += usage.cache_write_tokens

            if not assistant.tool_calls:
                final_message = assistant
                conversation.append(assistant)
                sink.emit(Event(kind=Kind.MESSAGE, text=assistant.content))
                break

            conversation.append(assistant)
            permission_results = await self._preflight_permissions(assistant.tool_calls)
            for tool_call, permission_result in zip(
                assistant.tool_calls, permission_results, strict=True
            ):
                output = await self._execute_tool(
                    sink, tool_call, permission_result=permission_result
                )
                conversation.append(
                    Message(
                        role=Role.TOOL,
                        tool_call_id=tool_call.id,
                        name=tool_call.name,
                        content=output,
                    )
                )
        else:
            error = f"Agent reached the maximum of {self.opts.max_steps} steps."
            sink.emit(Event(kind=Kind.ERROR, error=error))

        sink.emit(Event(kind=Kind.USAGE, usage=total_usage))
        sink.emit(Event(kind=Kind.TURN_DONE))
        return TurnResult(
            success=not error,
            error=error,
            message=final_message,
            usage=total_usage,
            steps=steps,
            messages=conversation[1:],
        )

    async def _call_llm(
        self,
        sink: Sink,
        messages: list[Message],
        tool_defs: list[dict[str, Any]],
    ) -> tuple[Message, UsageInfo | None]:
        full_text = ""
        full_reasoning = ""
        collected_tool_calls: list[ToolCall] = []
        last_event: StreamEvent | None = None

        sink.emit(Event(kind=Kind.PHASE, text=self.opts.provider.model_name))
        async for event in self.opts.provider.generate_stream(
            messages=messages,
            tools=tool_defs or None,
            temperature=self.opts.temperature,
        ):
            last_event = event
            if event.delta_reasoning:
                full_reasoning += event.delta_reasoning
                sink.emit(Event(kind=Kind.REASONING, reasoning=event.delta_reasoning))
            if event.delta_text:
                full_text += event.delta_text
                sink.emit(Event(kind=Kind.TEXT, text=event.delta_text))
            if event.tool_calls:
                collected_tool_calls = event.tool_calls
            if event.message:
                full_text = event.message.content
                full_reasoning = event.message.reasoning_content
                if event.message.tool_calls:
                    collected_tool_calls = event.message.tool_calls

        usage = UsageInfo()
        if last_event and last_event.usage:
            usage = UsageInfo(
                input_tokens=last_event.usage.input_tokens,
                output_tokens=last_event.usage.output_tokens,
                cache_read_tokens=last_event.usage.cache_read_tokens,
                cache_write_tokens=last_event.usage.cache_write_tokens,
            )
        return (
            Message(
                role=Role.ASSISTANT,
                content=full_text,
                reasoning_content=full_reasoning,
                tool_calls=collected_tool_calls,
            ),
            usage,
        )

    async def _preflight_permissions(
        self, tool_calls: list[ToolCall]
    ) -> list[tuple[bool, str] | None]:
        """Queue every approval in a model batch before executing any tool."""
        async def check(tool_call: ToolCall) -> tuple[bool, str] | None:
            tool = self.opts.registry.by_name(tool_call.name)
            if (
                tool is None
                or tool_call.name == "ask"
                or self.opts.permission_gate is None
            ):
                return None
            return await self.opts.permission_gate.check(
                tool_call.name,
                tool_call.args_json,
                read_only=tool.read_only,
            )

        return list(await asyncio.gather(*(check(call) for call in tool_calls)))

    async def _execute_tool(
        self,
        sink: Sink,
        tool_call: ToolCall,
        *,
        permission_result: tuple[bool, str] | None = None,
    ) -> str:
        tool = self.opts.registry.by_name(tool_call.name)
        if not tool:
            error = f"Unknown tool: {tool_call.name or '<empty>'}"
            sink.emit(
                Event(
                    kind=Kind.TOOL_RESULT,
                    tool=ToolCallInfo(
                        id=tool_call.id,
                        name=tool_call.name,
                        args_json=tool_call.args_json,
                        error=error,
                    ),
                )
            )
            return error

        if tool_call.name == "ask" and self.opts.ask_callback:
            return await self._execute_ask_tool(sink, tool_call, tool.read_only)

        if permission_result is not None:
            allowed, reason = permission_result
            if not allowed:
                error = f"Permission denied: {tool_call.name} — {reason}"
                sink.emit(
                    Event(
                        kind=Kind.TOOL_RESULT,
                        tool=ToolCallInfo(
                            id=tool_call.id,
                            name=tool_call.name,
                            args_json=tool_call.args_json,
                            read_only=tool.read_only,
                            error=error,
                        ),
                    )
                )
                return error

        change: Change | None = None
        if not tool.read_only:
            try:
                change = await tool.preview(tool_call.args_json)
            except Exception as exc:
                sink.emit(
                    Event(
                        kind=Kind.NOTICE,
                        level="warning",
                        text=f"Could not preview {tool_call.name}: {exc}",
                    )
                )
        info = ToolCallInfo(
            id=tool_call.id,
            name=tool_call.name,
            args_json=tool_call.args_json,
            read_only=tool.read_only,
            change=change,
        )
        sink.emit(Event(kind=Kind.TOOL_DISPATCH, tool=info))
        try:
            output = await tool.execute(tool_call.args_json)
            if len(output) > 32 * 1024:
                output = output[: 32 * 1024]
                info.truncated = True
            info.output = output
            sink.emit(Event(kind=Kind.TOOL_RESULT, tool=info))
            if (
                change is not None
                and not output.startswith("Error:")
                and self.opts.change_callback is not None
            ):
                self.opts.change_callback(tool_call.id, change)
            return output
        except Exception as exc:
            info.error = str(exc)
            sink.emit(Event(kind=Kind.TOOL_RESULT, tool=info))
            return f"Error: {exc}"

    async def _execute_ask_tool(
        self,
        sink: Sink,
        tool_call: ToolCall,
        read_only: bool,
    ) -> str:
        info = ToolCallInfo(
            id=tool_call.id,
            name=tool_call.name,
            args_json=tool_call.args_json,
            read_only=read_only,
        )
        sink.emit(Event(kind=Kind.TOOL_DISPATCH, tool=info))
        try:
            raw = json.loads(tool_call.args_json or "{}")
            questions = []
            for question in raw.get("questions", []):
                options = []
                for option in question.get("options", []):
                    label = option.get("label", "") if isinstance(option, dict) else str(option)
                    if label:
                        options.append(str(label))
                questions.append(
                    AskQuestion(
                        header=str(question.get("header", "")),
                        question=str(question.get("question", "")),
                        options=options,
                        multi_select=bool(question.get("multi_select", False)),
                    )
                )
            if not questions:
                questions = [
                    AskQuestion(
                        header="Question",
                        question="The agent requested input without a valid question.",
                        options=["Continue"],
                    )
                ]
            if self.opts.ask_callback is None:
                raise RuntimeError("No ask callback is configured")
            answers = await self.opts.ask_callback(questions)
            output = json.dumps({"answers": answers}, ensure_ascii=False)
            info.output = output
            sink.emit(Event(kind=Kind.TOOL_RESULT, tool=info))
            return output
        except Exception as exc:
            info.error = str(exc)
            sink.emit(Event(kind=Kind.TOOL_RESULT, tool=info))
            return f"Error: {exc}"
