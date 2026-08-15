"""OpenAI-compatible provider for OpenAI, DeepSeek, and compatible APIs."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_openai import ChatOpenAI

from reasonix.provider import (
    Message,
    Provider,
    ProviderConfig,
    Role,
    StreamEvent,
    ToolCall,
    Usage,
    register_provider,
)


def _content_to_text(message_or_content: Any) -> str:
    """Return provider-agnostic text from LangChain v1 content blocks."""
    if isinstance(message_or_content, BaseMessage):
        content = message_or_content.content
        blocks = getattr(message_or_content, "content_blocks", None)
        if blocks:
            texts: list[str] = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and block.get("text"):
                    texts.append(str(block["text"]))
            if texts:
                return "".join(texts)
    else:
        content = message_or_content

    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict):
                value = block.get("text") or block.get("content")
                if value:
                    texts.append(str(value))
        return "".join(texts)
    return str(content or "")


def _tool_args_for_langchain(args_json: str) -> dict[str, Any]:
    try:
        parsed = json.loads(args_json or "{}")
    except json.JSONDecodeError:
        return {"__raw_json": args_json}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _tool_name_from_langchain(tool_call: dict[str, Any]) -> str:
    if "name" in tool_call:
        return str(tool_call["name"] or "")
    function = tool_call.get("function", {})
    return str(function.get("name", ""))


def _tool_args_json_from_langchain(tool_call: dict[str, Any]) -> str:
    if "args" in tool_call:
        args = tool_call["args"]
        if isinstance(args, str):
            return args
        return json.dumps(
            args if args is not None else {},
            ensure_ascii=False,
            separators=(",", ":"),
        )
    function = tool_call.get("function", {})
    arguments = function.get("arguments", "{}")
    if isinstance(arguments, str):
        return arguments
    return json.dumps(
        arguments if arguments is not None else {},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _tool_calls_from_langchain(message: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for call in getattr(message, "tool_calls", None) or []:
        name = _tool_name_from_langchain(call)
        args_json = _tool_args_json_from_langchain(call)
        if not name:
            continue
        calls.append(
            ToolCall(
                id=str(call.get("id") or ""),
                name=name,
                args_json=args_json,
            )
        )
    return calls


def _to_lc_msg(msg: Message) -> BaseMessage:
    if msg.role == Role.SYSTEM:
        return SystemMessage(content=msg.content)
    if msg.role == Role.USER:
        return HumanMessage(content=msg.content)
    if msg.role == Role.ASSISTANT:
        kwargs: dict[str, Any] = {"content": msg.content}
        if msg.tool_calls:
            kwargs["tool_calls"] = [
                {
                    "id": tc.id,
                    "name": tc.name,
                    "args": _tool_args_for_langchain(tc.args_json),
                }
                for tc in msg.tool_calls
            ]
        return AIMessage(**kwargs)
    if msg.role == Role.TOOL:
        return ToolMessage(content=msg.content, tool_call_id=msg.tool_call_id)
    return HumanMessage(content=msg.content)


def _from_lc_msg(msg: BaseMessage) -> Message:
    if isinstance(msg, (AIMessage, AIMessageChunk)):
        return Message(
            role=Role.ASSISTANT,
            content=_content_to_text(msg),
            tool_calls=_tool_calls_from_langchain(msg),
        )
    if isinstance(msg, SystemMessage):
        return Message(role=Role.SYSTEM, content=_content_to_text(msg))
    if isinstance(msg, ToolMessage):
        return Message(
            role=Role.TOOL,
            content=_content_to_text(msg),
            tool_call_id=msg.tool_call_id,
        )
    return Message(role=Role.USER, content=_content_to_text(msg))


def _langchain_tool_defs(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize OpenAI or Anthropic schemas for LangChain bind_tools."""
    normalized = []
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        source = function if isinstance(function, dict) else tool
        name = source.get("name", "")
        if not name:
            continue
        normalized.append(
            {
                "name": name,
                "description": source.get("description", ""),
                "parameters": source.get("parameters") or source.get("input_schema") or {},
            }
        )
    return normalized


def _usage_from_metadata(metadata: Any) -> Usage:
    meta = metadata if isinstance(metadata, dict) else {}
    input_details = meta.get("input_token_details") or {}
    return Usage(
        input_tokens=int(meta.get("input_tokens", 0) or 0),
        output_tokens=int(meta.get("output_tokens", 0) or 0),
        cache_read_tokens=int(
            meta.get("cache_read_input_tokens", 0)
            or input_details.get("cache_read", 0)
            or 0
        ),
        cache_write_tokens=int(
            meta.get("cache_creation_input_tokens", 0)
            or input_details.get("cache_creation", 0)
            or 0
        ),
    )


class OpenAIProvider(Provider):
    """Provider backed by langchain-openai."""

    def __init__(
        self,
        model_name: str,
        api_key: str,
        base_url: str = "",
        **kwargs: Any,
    ) -> None:
        self._model_name = model_name
        llm_kwargs: dict[str, Any] = {
            "model": model_name,
            "api_key": api_key,
            "temperature": kwargs.get("temperature", 0.0),
        }
        if base_url:
            llm_kwargs["base_url"] = base_url
        if "max_tokens" in kwargs:
            llm_kwargs["max_tokens"] = kwargs["max_tokens"]
        self._llm = ChatOpenAI(**llm_kwargs)

    @classmethod
    def from_config(cls, config: ProviderConfig) -> OpenAIProvider:
        return cls(
            model_name=config.default_model,
            api_key=config.api_key,
            base_url=config.base_url,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    def _bound_model(
        self,
        tools: list[dict[str, Any]] | None,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        model = (
            self._llm.bind_tools(_langchain_tool_defs(tools)) if tools else self._llm
        )
        overrides: dict[str, Any] = {}
        if temperature is not None:
            overrides["temperature"] = temperature
        if max_tokens is not None:
            overrides["max_tokens"] = max_tokens
        return model.bind(**overrides) if overrides else model

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> tuple[Message, Usage]:
        result = await self._bound_model(
            tools, temperature=temperature, max_tokens=max_tokens
        ).ainvoke([_to_lc_msg(m) for m in messages])
        return _from_lc_msg(result), _usage_from_metadata(getattr(result, "usage_metadata", None))

    async def generate_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[StreamEvent]:
        aggregate: AIMessageChunk | None = None
        async for chunk in self._bound_model(
            tools, temperature=temperature, max_tokens=max_tokens
        ).astream([_to_lc_msg(m) for m in messages]):
            if not isinstance(chunk, AIMessageChunk):
                continue
            aggregate = chunk if aggregate is None else aggregate + chunk
            delta = _content_to_text(chunk)
            if delta:
                yield StreamEvent(delta_text=delta)

        if aggregate is None:
            yield StreamEvent(
                finish_reason="error",
                message=Message(role=Role.ASSISTANT),
                usage=Usage(),
            )
            return

        yield StreamEvent(
            finish_reason="stop",
            usage=_usage_from_metadata(aggregate.usage_metadata),
            message=_from_lc_msg(aggregate),
        )


def create_openai_provider(config: ProviderConfig) -> OpenAIProvider:
    return OpenAIProvider(
        model_name=config.default_model,
        api_key=config.api_key,
        base_url=config.base_url,
    )


register_provider("openai", OpenAIProvider)
