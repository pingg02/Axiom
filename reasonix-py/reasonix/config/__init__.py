"""
Configuration loader — TOML-based, multi-source resolution.

Resolution order: flag > ./reasonix.toml > desktop-managed config
> ~/.config/reasonix/config.toml > built-in defaults.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _user_config_dir() -> Path:
    """Return the Reasonix user config directory."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", "~/.config"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config"))
    return base.expanduser() / "reasonix"


def _find_project_config() -> Path | None:
    """Walk up from CWD to find reasonix.toml."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / "reasonix.toml"
        if candidate.is_file():
            return candidate
    return None


@dataclass
class UIConfig:
    theme: str = "auto"
    theme_style: str = "graphite"


@dataclass
class AgentConfig:
    max_steps: int = 50
    temperature: float = 0.0
    auto_plan: str = "off"
    compact_ratio: float = 0.8
    compact_force_ratio: float = 0.9
    soft_compact_ratio: float = 0.5
    tool_result_snip_ratio: float = 0.6
    planner_model: str = ""
    subagent_model: str = ""
    memory_compiler: bool = True
    reasoning_language: str = "auto"


@dataclass
class ProviderEntry:
    kind: str = "openai"
    api_key_env: str = ""
    base_url: str = ""
    default_model: str = ""
    models: list[str] = field(default_factory=list)


@dataclass
class ServeConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    auth_required: bool = False


@dataclass
class DesktopConfig:
    layout_style: str = "classic"


@dataclass
class Config:
    default_model: str = "deepseek"
    language: str = ""
    ui: UIConfig = field(default_factory=UIConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    desktop: DesktopConfig = field(default_factory=DesktopConfig)
    serve: ServeConfig = field(default_factory=ServeConfig)
    providers: dict[str, ProviderEntry] = field(default_factory=dict)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)
    additional_system_prompt: str = ""
    _source_path: str = ""

    @classmethod
    def load_defaults(cls) -> Config:
        return cls()

    @classmethod
    def load(cls, path: str | None = None) -> Config:
        """Load config from file, merging with defaults."""
        cfg = cls.load_defaults()

        # 1. User-level config
        user_cfg = _user_config_dir() / "config.toml"
        if user_cfg.is_file():
            cfg._merge_toml(user_cfg)

        # 2. Desktop-managed provider metadata. API keys are never stored here;
        # Electron decrypts them from the OS-protected secret store and passes
        # only the selected provider's environment variable to this process.
        desktop_config = os.environ.get("REASONIX_DESKTOP_CONFIG", "")
        if desktop_config:
            desktop_path = Path(desktop_config).expanduser()
            if desktop_path.is_file():
                cfg._merge_toml(desktop_path)

        # 3. Project-level config
        project_path: Path | None
        if path:
            project_path = Path(path)
        else:
            project_path = _find_project_config()
        if project_path and project_path.is_file():
            cfg._source_path = str(project_path)
            cfg._merge_toml(project_path)

        return cfg

    def _merge_toml(self, path: Path) -> None:
        """Merge a TOML file into this config (shallow merge for now)."""
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))

        if "default_model" in data:
            self.default_model = data["default_model"]
        if "language" in data:
            self.language = data["language"]
        if "additional_system_prompt" in data:
            self.additional_system_prompt = data["additional_system_prompt"]

        if "ui" in data:
            for k, v in data["ui"].items():
                if hasattr(self.ui, k):
                    setattr(self.ui, k, v)

        if "agent" in data:
            for k, v in data["agent"].items():
                if hasattr(self.agent, k):
                    setattr(self.agent, k, v)

        if "desktop" in data:
            for k, v in data["desktop"].items():
                if hasattr(self.desktop, k):
                    setattr(self.desktop, k, v)

        if "serve" in data:
            for k, v in data["serve"].items():
                if hasattr(self.serve, k):
                    setattr(self.serve, k, v)

        if "mcp_servers" in data and isinstance(data["mcp_servers"], dict):
            self.mcp_servers = {
                str(name): dict(server)
                for name, server in data["mcp_servers"].items()
                if isinstance(server, dict)
            }

        if "providers" in data:
            self._merge_providers(data["providers"])

    def _merge_providers(self, providers: Any) -> None:
        """Merge provider config from table or [[providers]] array syntax."""
        iterable: Iterable[tuple[Any, Any]]
        if isinstance(providers, dict):
            iterable = providers.items()
        elif isinstance(providers, list):
            iterable = (
                (entry.get("name", entry.get("kind", f"provider_{idx}")), entry)
                for idx, entry in enumerate(providers)
                if isinstance(entry, dict)
            )
        else:
            return

        for name, entry in iterable:
            if not isinstance(entry, dict):
                continue
            resolved = ProviderEntry(kind=entry.get("kind", "openai"))
            for k in ("api_key_env", "base_url", "default_model"):
                if k in entry:
                    setattr(resolved, k, entry[k])
            if "model" in entry and not resolved.default_model:
                resolved.default_model = entry["model"]
            if "default" in entry and not resolved.default_model:
                resolved.default_model = entry["default"]
            if "models" in entry:
                resolved.models = entry["models"]
            self.providers[str(name)] = resolved

    def resolve_api_key(self, provider_name: str) -> str:
        """Resolve the API key for a provider from environment."""
        entry = self.providers.get(provider_name)
        if not entry or not entry.api_key_env:
            return os.environ.get(f"{provider_name.upper()}_API_KEY", "")
        return os.environ.get(entry.api_key_env, "")
