import asyncio
import json
import subprocess
import sys
import time

from reasonix.tool.builtin.bash import BashTool


def test_bash_timeout_kills_process_tree(tmp_path):
    marker = tmp_path / "still-running.txt"
    script = (
        "import pathlib, time; "
        "time.sleep(1.0); "
        f"pathlib.Path(r'{marker}').write_text('done')"
    )
    command = subprocess.list2cmdline([sys.executable, "-c", script])

    output = asyncio.run(
        BashTool().execute(json.dumps({"command": command, "timeout_seconds": 0.1}))
    )
    time.sleep(1.5)

    assert "Command timed out after 0.1s" in output
    assert not marker.exists()
