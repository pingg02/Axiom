import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent


def test_pyinstaller_spec_does_not_exclude_runtime_dependencies():
    spec_text = (PROJECT_ROOT / "reasonix_min.spec").read_text(encoding="utf-8")

    assert "'typing_extensions'" not in spec_text
    assert '"typing_extensions"' not in spec_text


def test_pyproject_declares_imported_provider_dependencies():
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]

    assert (PROJECT_ROOT / pyproject["project"]["readme"]).is_file()
    assert any(dep.startswith("typing_extensions") for dep in dependencies)
    assert any(dep.startswith("langchain-openai") for dep in dependencies)
    assert any(dep.startswith("langchain-anthropic") for dep in dependencies)


def test_build_script_installs_project_dependencies_before_pyinstaller():
    build_script = (REPO_ROOT / "build_all.ps1").read_text(encoding="utf-8")

    assert "& $pythonExe @pythonPrefix -m pip install -e . pyinstaller" in build_script
    assert '$pythonPrefix = @("-3")' in build_script
    assert 'reasonix.exe") --version' in build_script
    assert "start_reasonix_desktop.cmd" in build_script
    assert "desktop-electron" in build_script
    assert "npm run build" in build_script
    assert "Fresh build left at:" in build_script
    assert "Read-Host" not in build_script


def test_launcher_scripts_use_bundled_artifacts_and_ascii_text():
    scripts = (
        "start_reasonix.cmd",
        "start_reasonix_full.cmd",
        "start_reasonix_desktop.cmd",
    )
    for script_name in scripts:
        script_text = (REPO_ROOT / script_name).read_text(encoding="utf-8")
        script_text.encode("ascii")
        assert "reasonix-py" not in script_text
        assert "%REASONIX_HOME%reasonix.exe" in script_text


def test_desktop_launcher_opens_bundled_frontend_route():
    script_text = (REPO_ROOT / "start_reasonix_desktop.cmd").read_text(encoding="utf-8")
    assert "http://127.0.0.1:8080/desktop" in script_text
    assert '"%PYTHON_EXE%" serve' in script_text


def test_launcher_scripts_explain_missing_deepseek_key_before_chat():
    for script_name in ("start_reasonix.cmd", "start_reasonix_full.cmd"):
        script_text = (REPO_ROOT / script_name).read_text(encoding="utf-8")
        assert "DEEPSEEK_API_KEY is not set, so chat cannot start" in script_text
        assert "set DEEPSEEK_API_KEY=your_api_key_here" in script_text
        assert "exit /b 2" in script_text
