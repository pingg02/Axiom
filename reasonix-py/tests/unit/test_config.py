from reasonix.config import Config


def test_config_loads_array_style_providers(tmp_path):
    config_path = tmp_path / "reasonix.toml"
    config_path.write_text(
        """
default_model = "deepseek"

[[providers]]
name = "deepseek"
kind = "openai"
base_url = "https://api.deepseek.com"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"

[[providers]]
name = "openai"
kind = "openai"
default = "gpt-4.1"
models = ["gpt-4.1", "gpt-4.1-mini"]
api_key_env = "OPENAI_API_KEY"
""",
        encoding="utf-8",
    )

    cfg = Config.load(str(config_path))

    assert cfg.providers["deepseek"].default_model == "deepseek-chat"
    assert cfg.providers["deepseek"].base_url == "https://api.deepseek.com"
    assert cfg.providers["openai"].default_model == "gpt-4.1"
    assert cfg.providers["openai"].models == ["gpt-4.1", "gpt-4.1-mini"]


def test_config_loads_current_mcp_server_shape(tmp_path):
    config_path = tmp_path / "reasonix.toml"
    config_path.write_text(
        """
[mcp_servers.files]
transport = "stdio"
command = "python"
args = ["-m", "example_mcp"]

[mcp_servers.docs]
transport = "http"
url = "https://mcp.example.test/mcp"
""",
        encoding="utf-8",
    )

    cfg = Config.load(str(config_path))

    assert cfg.mcp_servers["files"]["command"] == "python"
    assert cfg.mcp_servers["files"]["args"] == ["-m", "example_mcp"]
    assert cfg.mcp_servers["docs"]["transport"] == "http"


def test_config_loads_desktop_provider_metadata_without_inline_secret(
    monkeypatch, tmp_path
):
    desktop_config = tmp_path / "provider.toml"
    desktop_config.write_text(
        """
default_model = "deepseek"

[providers.deepseek]
kind = "openai"
base_url = "https://api.deepseek.com"
default_model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("REASONIX_DESKTOP_CONFIG", str(desktop_config))
    monkeypatch.chdir(tmp_path)

    cfg = Config.load()

    assert cfg.default_model == "deepseek"
    assert cfg.providers["deepseek"].api_key_env == "DEEPSEEK_API_KEY"
    assert "\napi_key =" not in desktop_config.read_text(encoding="utf-8")
