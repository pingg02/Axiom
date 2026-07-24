"""Verify the full import chain works."""

import sys
import traceback

from reasonix.agent.compose import ComposeInput, compose_system_prompt
from reasonix.boot import _default_tools
from reasonix.provider import PROVIDER_FACTORIES

try:
    # Verify built-in tools can be created
    reg = _default_tools()
    tool_names = sorted(reg._tools.keys())
    print(f"Built-in tools: {tool_names}")
    for name in tool_names:
        tool = reg._tools[name]
        assert tool.name == name, f"Tool name mismatch: {name}"
        assert tool.description, f"Tool {name} missing description"
        assert tool.schema, f"Tool {name} missing schema"

    # Verify provider factories
    print(f"Registered providers: {list(PROVIDER_FACTORIES.keys())}")
    if not PROVIDER_FACTORIES:
        print("WARNING: no providers registered — openai/anthropic imports may be missing")

    # Verify compose with snapshot
    snap = reg.snapshot()
    inp = ComposeInput(registry_snapshot=snap)
    prompt = compose_system_prompt(inp)
    assert "BASE_PROMPT" in prompt or "You are Reasonix" in prompt
    assert "bash" in prompt.lower()
    print(f"System prompt: {len(prompt)} chars, {prompt.count(chr(10))} lines")

    print("\nAll checks passed!")
except Exception as e:
    print(f"FAILED: {e}")
    traceback.print_exc()
    sys.exit(1)
