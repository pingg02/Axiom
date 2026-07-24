"""CLI error-handling tests."""



def test_run_command_prints_friendly_config_error_without_traceback(monkeypatch, capsys):
    """Missing provider setup should be a user-facing error, not a PyInstaller crash."""
    import reasonix.boot as boot
    import reasonix.cli.cli as cli

    assert hasattr(boot, "ConfigError")

    def fake_build_controller(*args, **kwargs):
        raise boot.ConfigError("Missing API key for provider 'deepseek'. Set DEEPSEEK_API_KEY.")

    monkeypatch.setattr(cli, "build_controller", fake_build_controller)

    exit_code = cli.main(["run", "hello"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Missing API key" in captured.err
    assert "DEEPSEEK_API_KEY" in captured.err
    assert "Traceback" not in captured.err


def test_run_command_prints_friendly_unexpected_error_without_traceback(monkeypatch, capsys):
    """Unexpected startup failures should still avoid raw tracebacks in bundled exe mode."""
    import reasonix.cli.cli as cli

    def fake_build_controller(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "build_controller", fake_build_controller)

    exit_code = cli.main(["run", "hello"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Reasonix failed to start" in captured.err
    assert "boom" in captured.err
    assert "Traceback" not in captured.err


def test_desktop_command_accepts_host_and_port_arguments():
    """Electron can launch an isolated desktop bridge instead of fighting for 9092."""
    from reasonix.cli.cli import build_parser

    args = build_parser().parse_args(["desktop", "--host", "127.0.0.1", "--port", "9333"])

    assert args.command == "desktop"
    assert args.host == "127.0.0.1"
    assert args.port == 9333
