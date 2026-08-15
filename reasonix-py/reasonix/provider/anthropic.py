"""Anthropic provider backed by langchain-anthropic."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessageChunk

from reasonix.provider import (
    Message,
    Provider,
    ProviderConfig,
    Role,
    StreamEvent,
    Usage,
    register_provider,
)
from reasonix.provider.openai import (
    _content_to_text,
    _from_lc_msg,
    _langchain_tool_defs,
    _to_lc_msg,
    _usage_from_metadata,
)


class AnthropicProvider(Provider):
    """Provider backed by langchain-anthropic with LangChain v1 tool shapes."""

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
        self._llm = ChatAnthropic(**llm_kwargs)

    @classmethod
    def from_config(cls, config: ProviderConfig) -> AnthropicProvider:
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


def create_anthropic_provider(config: ProviderConfig) -> AnthropicProvider:
    return AnthropicProvider(
        model_name=config.default_model,
        api_key=config.api_key,
        base_url=config.base_url,
    )


register_provider("anthropic", AnthropicProvider)
