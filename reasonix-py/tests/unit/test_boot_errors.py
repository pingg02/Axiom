"""Boot-time diagnostics tests."""

import pytest

from reasonix.config import Config, ProviderEntry


def test_build_provider_reports_missing_api_key_before_openai_sdk(monkeypatch):
    """Provider setup should fail with actionable config guidance when the key env is absent."""
    import reasonix.boot as boot

    assert hasattr(boot, "ConfigError")

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = Config(
        default_model="deepseek",
        providers={
            "deepseek": ProviderEntry(
                kind="openai",
                api_key_env="DEEPSEEK_API_KEY",
                base_url="https://api.deepseek.com",
                default_model="deepseek-chat",
            )
        },
    )

    with pytest.raises(boot.ConfigError) as exc:
        boot._build_provider(cfg)

    message = str(exc.value)
    assert "Missing API key" in message
    assert "deepseek" in message
    assert "DEEPSEEK_API_KEY" in message
    assert "reasonix.toml" in message


def test_build_provider_supports_provider_slash_model_refs(monkeypatch):
    """default_model='provider/model' should select that provider and override the model."""
    import reasonix.boot as boot

    class FakeProvider:
        def __init__(self, model_name, api_key, base_url):
            self.model_name = model_name
            self.api_key = api_key
            self.base_url = base_url

    monkeypatch.setitem(boot.PROVIDER_FACTORIES, "fake", FakeProvider)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    cfg = Config(
        default_model="deepseek/deepseek-v4-flash",
        providers={
            "deepseek": ProviderEntry(
                kind="fake",
                api_key_env="DEEPSEEK_API_KEY",
                base_url="https://api.deepseek.com",
                default_model="deepseek-chat",
            )
        },
    )

    provider = boot._build_provider(cfg)

    assert provider.model_name == "deepseek-v4-flash"
    assert provider.api_key == "test-key"
