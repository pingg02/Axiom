"""
Boot — assembly factory for the whole Reasonix application.

Takes a config + sink and wires up:
  config → provider → tool registry → memory → controller
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, cast

import reasonix.provider.anthropic  # noqa: F401

# Side-effect imports: these register provider classes via init-time calls
import reasonix.provider.openai  # noqa: F401
from reasonix.config import Config
from reasonix.control.controller import Controller, ControllerOptions
from reasonix.event import Sink
from reasonix.grpc import SecurityClient
from reasonix.history import SessionStore
from reasonix.memory import MemoryDoc, MemorySet
from reasonix.permission.permission import Gate, Policy
from reasonix.provider import PROVIDER_FACTORIES, Provider
from reasonix.skill import discover_skills, format_skill_catalog
from reasonix.tool.registry import Registry

logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """User-actionable configuration/startup error."""


def _default_tools() -> Registry:
    """Register and return the built-in tools."""
    from reasonix.tool.builtin import BUILTIN_TOOL_CLASSES
    reg = Registry()
    for tool_cls in BUILTIN_TOOL_CLASSES:
        reg.add(tool_cls())
    return reg


def _build_provider(config: Config) -> Provider:
    """Build the primary provider from config."""
    model_ref = config.default_model
    model_override = ""
    entry = config.providers.get(model_ref)

    if entry is None and "/" in model_ref:
        provider_name, selected_model = model_ref.split("/", 1)
        slash_entry = config.providers.get(provider_name)
        if slash_entry is not None:
            entry = slash_entry
            model_ref = provider_name
            model_override = selected_model

    if entry is None:
        # Fallback: try to find any configured provider
        for name, pe in config.providers.items():
            entry = pe
            model_ref = name
            break

    if entry is None:
        raise ConfigError(
            f"No provider found for model '{model_ref}'. "
            "Add a [[providers]] entry to reasonix.toml."
        )

    # Resolve the API key
    api_key = config.resolve_api_key(model_ref)
    if not api_key:
        api_key = os.environ.get(f"{model_ref.upper()}_API_KEY", "")
    if not api_key:
        env_name = entry.api_key_env or f"{model_ref.upper()}_API_KEY"
        raise ConfigError(
            f"Missing API key for provider '{model_ref}'. "
            f"Set the {env_name} environment variable or edit reasonix.toml "
            f"to point api_key_env at the variable that contains your key."
        )

    # Find provider class
    provider_cls = PROVIDER_FACTORIES.get(entry.kind)
    if provider_cls is None:
        raise ConfigError(
            f"Unknown provider kind '{entry.kind}' for '{model_ref}'. "
            f"Available: {list(PROVIDER_FACTORIES.keys())}"
        )

    # Build config object for the provider factory
    from reasonix.provider import ProviderConfig
    prov_cfg = ProviderConfig(
        kind=entry.kind,
        api_key=api_key,
        base_url=entry.base_url,
        default_model=model_override or entry.default_model,
        models=entry.models,
    )

    factory = cast(Any, provider_cls)
    built: object
    if "from_config" in provider_cls.__dict__:
        built = factory.from_config(prov_cfg)
    else:
        # Compatibility boundary for third-party providers registered before
        # Provider.from_config() became the preferred factory protocol.
        built = factory(
            model_name=model_override or entry.default_model,
            api_key=api_key,
            base_url=entry.base_url,
        )
    return cast(Provider, built)


def _load_memory(config: Config) -> MemorySet:
    """Discover and load memory documents."""
    mem = MemorySet()

    # 1. Project-level REASONIX.md
    cwd = Path.cwd()
    for name in ("REASONIX.md", "AGENTS.md"):
        candidate = cwd / name
        if candidate.is_file():
            mem.add(MemoryDoc(
                source=str(candidate),
                content=candidate.read_text(encoding="utf-8"),
                mtime=candidate.stat().st_mtime,
            ))
            break

    # 2. User-level REASONIX.md
    user_dir = Path.home() / ".config" / "reasonix"
    user_file = user_dir / "REASONIX.md"
    if user_file.is_file():
        mem.add(MemoryDoc(
            source=str(user_file),
            content=user_file.read_text(encoding="utf-8"),
            mtime=user_file.stat().st_mtime,
        ))

    return mem


def build_controller(
    config: Config | None = None,
    sink: Sink | None = None,
    history_store: SessionStore | None = None,
    **overrides: str,
) -> Controller:
    """Build a fully-wired Controller from config.

    This is the main entry point for all frontends (CLI, serve, desktop).
    """
    cfg = config or Config.load()
    if cfg.mcp_servers:
        logger.warning(
            "MCP servers are configured but synchronous startup cannot load them; "
            "use build_controller_async()."
        )
    return _assemble_controller(
        cfg,
        sink,
        _default_tools(),
        history_store=history_store,
    )


def _assemble_controller(
    cfg: Config,
    sink: Sink | None,
    registry: Registry,
    *,
    resources: list[object] | None = None,
    mcp_statuses: list[object] | None = None,
    history_store: SessionStore | None = None,
    security_client: SecurityClient | None = None,
    security_required: bool = False,
    security_error: str = "",
) -> Controller:
    provider = _build_provider(cfg)
    skills = discover_skills(Path.cwd())
    skill_catalog = format_skill_catalog(skills)
    additional_prompt = "\n\n".join(
        part for part in (cfg.additional_system_prompt, skill_catalog) if part
    )
    opts = ControllerOptions(
        registry=registry.snapshot(),
        provider=provider,
        memory=_load_memory(cfg),
        sink=sink,
        max_steps=cfg.agent.max_steps,
        temperature=cfg.agent.temperature,
        language=cfg.language,
        additional_prompt=additional_prompt,
        permission_gate=Gate(Policy()),
        resources=resources or [],
        mcp_statuses=mcp_statuses or [],
        skills=skills,
        provider_name=cfg.default_model.split("/", 1)[0],
        provider_model=provider.model_name,
        history_store=history_store,
        workspace=str(Path.cwd()),
        security_client=security_client,
        security_required=security_required,
        security_error=security_error,
    )

    return Controller(opts)


def build_unconfigured_controller(
    error: str,
    sink: Sink | None = None,
    history_store: SessionStore | None = None,
) -> Controller:
    """Build a desktop-safe controller that can report missing provider setup."""
    cfg = Config.load()
    skills = discover_skills(Path.cwd())
    skill_catalog = format_skill_catalog(skills)
    additional_prompt = "\n\n".join(
        part for part in (cfg.additional_system_prompt, skill_catalog) if part
    )
    return Controller(
        ControllerOptions(
            registry=_default_tools().snapshot(),
            memory=_load_memory(cfg),
            sink=sink,
            max_steps=cfg.agent.max_steps,
            temperature=cfg.agent.temperature,
            language=cfg.language,
            additional_prompt=additional_prompt,
            permission_gate=Gate(Policy()),
            configuration_error=error,
            skills=skills,
            history_store=history_store,
            workspace=str(Path.cwd()),
        )
    )


async def build_controller_async(
    config: Config | None = None,
    sink: Sink | None = None,
    history_store: SessionStore | None = None,
    **overrides: str,
) -> Controller:
    """Build a controller and discover configured MCP tools asynchronously."""
    cfg = config or Config.load()
    registry = _default_tools()
    resources: list[object] = []
    statuses: list[object] = []
    security_client: SecurityClient | None = None
    security_error = ""
    security_required = os.environ.get("AXIOM_SECURITY_REQUIRED", "").lower() in {
        "1", "true", "yes"
    }
    security_port = os.environ.get("AXIOM_SECURITY_PORT", "").strip()
    security_token = os.environ.get("AXIOM_SECURITY_TOKEN", "").strip()
    if security_required:
        if not security_port.isdigit() or not security_token:
            security_error = "Java security service startup information is missing"
        else:
            security_client = SecurityClient(
                host="127.0.0.1",
                port=int(security_port),
                token=security_token,
            )
            if await security_client.connect():
                resources.append(security_client)
            else:
                security_error = "Java security service is unavailable"
                security_client = None
    if cfg.mcp_servers:
        from reasonix.tool.mcp_loader import register_mcp_tools

        client, mcp_statuses = await register_mcp_tools(registry, cfg.mcp_servers)
        statuses.extend(mcp_statuses)
        if client is not None:
            resources.append(client)
    return _assemble_controller(
        cfg,
        sink,
        registry,
        resources=resources,
        mcp_statuses=statuses,
        history_store=history_store,
        security_client=security_client,
        security_required=security_required,
        security_error=security_error,
    )
