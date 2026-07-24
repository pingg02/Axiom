"""Electron packaging contract tests."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ELECTRON_DIR = ROOT / "desktop" / "electron"


def test_electron_builder_points_at_pyinstaller_output():
    """electron-builder should include the PyInstaller exe from the real repo path."""
    package = json.loads((ELECTRON_DIR / "package.json").read_text(encoding="utf-8"))

    resource = package["build"]["extraResources"][0]
    assert resource["from"] == "../../reasonix-py/dist/reasonix.exe"
    assert resource["to"] == "reasonix-server.exe"


def test_electron_main_dev_build_path_points_at_real_pyinstaller_dist():
    """main.js should look two levels up from desktop/electron in dev mode."""
    main_js = (ELECTRON_DIR / "main.js").read_text(encoding="utf-8")

    assert "path.join(__dirname, '..', '..', 'reasonix-py', 'dist', 'reasonix.exe')" in main_js


def test_electron_main_exposes_openai_and_anthropic_compatible_presets():
    """Provider setup should not force every compatible endpoint through OpenAI format."""
    main_js = (ELECTRON_DIR / "main.js").read_text(encoding="utf-8")

    assert "deepseek_anthropic" in main_js
    assert "anthropic_compatible" in main_js
    assert "kind: 'openai'" in main_js
    assert "kind: 'anthropic'" in main_js
    assert "https://api.deepseek.com/anthropic" in main_js
    assert "normalizeProviderSetup" in main_js


def test_build_script_populates_electron_frontend_from_vite_dist():
    """The main build script should copy the Vite frontend into Electron's package files."""
    build_script = (ROOT / "build_all.ps1").read_text(encoding="utf-8")

    assert 'desktop\\electron\\frontend' in build_script
    assert 'Copy-Item -Recurse "dist\\*"' in build_script


def test_vite_frontend_uses_loopback_when_loaded_from_file_url():
    """Electron loadFile has no hostname, so the WebSocket URL needs a loopback fallback."""
    app_tsx = (ROOT / "desktop" / "python-frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )

    assert "location.hostname || '127.0.0.1'" in app_tsx


def test_vite_frontend_can_send_approval_decisions():
    """The desktop frontend should render approval requests and send approve actions."""
    app_tsx = (ROOT / "desktop" / "python-frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )

    assert "approval_request" in app_tsx
    assert "action: 'approve'" in app_tsx
    assert "request_id" in app_tsx


def test_electron_package_does_not_reference_missing_icons():
    """electron-builder should not fail because package.json references absent icon files."""
    package = json.loads((ELECTRON_DIR / "package.json").read_text(encoding="utf-8"))
    build = package["build"]

    for section_name in ("win", "mac"):
        section = build.get(section_name, {})
        icon = section.get("icon")
        assert not icon or (ELECTRON_DIR / icon).is_file()


def test_vite_build_uses_relative_asset_paths_for_electron_file_protocol():
    """Electron loadFile needs Vite assets to resolve relative to index.html."""
    vite_config = (ROOT / "desktop" / "python-frontend" / "vite.config.ts").read_text(
        encoding="utf-8"
    )

    assert "base: './'" in vite_config


def test_electron_main_uses_dynamic_desktop_bridge_port_and_workspace_cwd():
    """Packaged desktop launches its own bridge port and exposes cwd to the UI."""
    main_js = (ELECTRON_DIR / "main.js").read_text(encoding="utf-8")

    assert "getFreePort(9092)" in main_js
    assert "REASONIX_WORKSPACE" in main_js
    assert "cwd: workspaceCwd" in main_js
    assert "reasonix-py" in main_js
    assert "build_all.ps1" in main_js
    assert "wsPort: String(bridgePort)" in main_js
    assert "waitForBridge(bridgePort)" in main_js


def test_desktop_frontend_has_workbench_modules_and_tool_result_upsert():
    """Desktop UI should expose modules and update tool result cards by id, not position."""
    app_tsx = (ROOT / "desktop" / "python-frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )

    for label in ("对话", "工具", "工作区", "会话", "设置", "诊断"):
        assert label in app_tsx
    assert "params.get('wsPort')" in app_tsx
    assert "toolId" in app_tsx
    assert "upsertToolRun" in app_tsx
    assert "setActiveModule('tools')" not in app_tsx
    assert "setInterval" in app_tsx
    assert "WebSocket.CONNECTING" in app_tsx


def test_desktop_frontend_exposes_ask_allow_deny_controls():
    """Interactive approval and ask flows must have visible frontend controls."""
    app_tsx = (ROOT / "desktop" / "python-frontend" / "src" / "App.tsx").read_text(
        encoding="utf-8"
    )

    assert "approval_request" in app_tsx
    assert "ask_request" in app_tsx
    assert "action: 'approve'" in app_tsx
    assert "action: 'answer_ask'" in app_tsx
    assert "onAnswerAsk" in app_tsx
    assert "提交回答" in app_tsx
    assert "is-selected" in app_tsx
    assert "允许" in app_tsx
    assert "拒绝" in app_tsx
