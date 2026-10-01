"""Real detached process tests; Windows UI CI must not pretend to run Linux jobs."""

import base64
import json
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from reasonix.experiments import worker

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux remote worker")


def operate(payload, action):
    source = base64.b64encode(Path(worker.__file__).read_bytes()).decode()
    result = subprocess.run(
        [sys.executable, worker.__file__, json.dumps(payload), source, action],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return json.loads(result.stdout.split("AXIOM_JOB=", 1)[1])


def poll(payload, states):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = operate(payload, "status")
        if result["state"] in states:
            return result
        time.sleep(0.05)
    pytest.fail(f"Job did not reach {states}")


def test_detached_job_captures_log_checkpoint_and_exit(tmp_path):
    script = (
        "import os,pathlib;print('epoch 1');"
        "pathlib.Path(os.environ['AXIOM_OUTPUT_DIR'],'model.pt').write_text('test')"
    )
    payload = {
        "id": "exp_" + uuid.uuid4().hex,
        "directory": str(tmp_path),
        "name": "smoke",
        "config_path": "config.yaml",
        "command": shlex.quote(sys.executable) + " -c " + shlex.quote(script),
    }
    submitted = operate(payload, "submit")
    assert submitted["id"] == payload["id"]
    result = poll(payload, {"completed", "failed"})
    assert result["state"] == "completed"
    assert result["exit_code"] == 0
    assert "epoch 1" in result["log_tail"]
    assert result["checkpoints"] == ["model.pt"]
    with pytest.raises(subprocess.CalledProcessError):
        operate(payload, "submit")


def test_stop_only_targets_owned_job_process_group(tmp_path):
    payload = {
        "id": "exp_" + uuid.uuid4().hex,
        "directory": str(tmp_path),
        "name": "cancel",
        "config_path": "",
        "command": shlex.quote(sys.executable) + " -c " + shlex.quote("import time;time.sleep(30)"),
    }
    operate(payload, "submit")
    poll(payload, {"running"})
    result = operate(payload, "stop")
    assert result["state"] == "stopping"
    assert poll(payload, {"cancelled"})["state"] == "cancelled"
