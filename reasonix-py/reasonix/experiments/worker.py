"""Small dependency-free Linux job supervisor, sent to the remote Python 3.

It does not require an Axiom installation on the GPU server. Only commands
explicitly submitted by the user are run; this is not an agent permission bypass.
"""

from __future__ import annotations

import base64
import json
import os
import re
import signal
import subprocess
import sys
import time
from itertools import islice
from pathlib import Path
from typing import Any


def start_ticks(pid: int) -> str:
    try:
        # comm may contain spaces/parentheses, so split after its final ')'.
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return "" if fields[0] in {"Z", "X"} else fields[19]
    except (OSError, IndexError):
        return ""


def main() -> None:
    if sys.platform != "linux":
        raise RuntimeError("The remote experiment supervisor requires Linux")
    import fcntl

    payload = json.loads(sys.argv[1])
    source = sys.argv[2]
    action = sys.argv[3]
    experiment_id = payload["id"]
    if not re.fullmatch(r"exp_[0-9a-f]{32}", experiment_id):
        raise ValueError("Invalid experiment ID")
    workspace = Path(payload["directory"]).resolve(strict=True)
    root = workspace / ".axiom" / "experiments"
    root.mkdir(parents=True, exist_ok=True)
    if not root.resolve().is_relative_to(workspace):
        raise ValueError("Experiment directory escapes workspace")
    folder = root / experiment_id
    if action == "submit":
        folder.mkdir(exist_ok=False)
    if not folder.resolve(strict=True).is_relative_to(root.resolve()):
        raise ValueError("Experiment path escapes storage root")
    metadata = folder / "job.json"

    def save(record: dict[str, Any]) -> None:
        temporary = folder / "job.tmp"
        temporary.write_text(json.dumps(record, ensure_ascii=False))
        temporary.replace(metadata)

    def load() -> dict[str, Any]:
        result: dict[str, Any] = json.loads(metadata.read_text())
        if result["id"] != experiment_id or result["directory"] != str(workspace):
            raise ValueError("Job identity mismatch")
        return result

    with (folder / "job.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if action == "submit":

            def git(*arguments: str) -> str:
                result = subprocess.run(
                    ["git", *arguments],
                    cwd=workspace,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                return result.stdout.strip() if result.returncode == 0 else ""

            record = {
                **payload,
                "directory": str(workspace),
                "state": "submitted",
                "created_at": time.time(),
                "pid": 0,
                "start_ticks": "",
                "branch": git("branch", "--show-current"),
                "commit": git("rev-parse", "HEAD"),
                "dirty": bool(git("status", "--porcelain", "--", ".", ":(exclude).axiom")),
                "log_path": str(folder / "train.log"),
                "output_dir": str(folder),
            }
            save(record)
            supervisor = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    base64.b64decode(source).decode(),
                    sys.argv[1],
                    source,
                    "run",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
            record.update(
                supervisor_pid=supervisor.pid, supervisor_start_ticks=start_ticks(supervisor.pid)
            )
            save(record)
        else:
            record = load()
        if action not in {"submit", "status", "stop", "run"}:
            raise ValueError("Invalid job action")
        if action == "run":
            if record["state"] == "cancelled":
                return
            environment = dict(
                os.environ, AXIOM_EXPERIMENT_ID=experiment_id, AXIOM_OUTPUT_DIR=str(folder)
            )
            with (folder / "train.log").open("ab") as log:
                process = subprocess.Popen(
                    ["bash", "-lc", record["command"]],
                    cwd=workspace,
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            record.update(
                state="running",
                pid=process.pid,
                start_ticks=start_ticks(process.pid),
                started_at=time.time(),
            )
            save(record)
            fcntl.flock(lock, fcntl.LOCK_UN)
            exit_code = process.wait()
            fcntl.flock(lock, fcntl.LOCK_EX)
            record = load()
            if record["state"] == "stopping":
                record["state"] = "cancelled"
            elif record["state"] != "cancelled":
                record["state"] = "completed" if exit_code == 0 else "failed"
            record.update(exit_code=exit_code, finished_at=time.time())
            save(record)
            return
        if action == "stop" and record["state"] in {"submitted", "running"}:
            pid = record["pid"]
            if pid and record["start_ticks"]:
                if pid <= 1 or os.getpgid(pid) != pid:
                    raise ValueError("Refusing to signal an unowned process group")
                if start_ticks(pid) != record["start_ticks"]:
                    raise ValueError("Process identity changed; refusing to signal it")
                os.killpg(pid, signal.SIGTERM)
            record["state"] = "stopping" if pid else "cancelled"
            save(record)
        if record["state"] == "running" and start_ticks(record["pid"]) != record["start_ticks"]:
            record["state"] = "unknown"
            save(record)
        if record["state"] == "submitted" and start_ticks(
            record.get("supervisor_pid", 0)
        ) != record.get("supervisor_start_ticks", ""):
            record["state"] = "unknown"
            save(record)
        log_path = folder / "train.log"
        if log_path.is_file():
            with log_path.open("rb") as log:
                log.seek(max(0, log_path.stat().st_size - 8192))
                record["log_tail"] = log.read(8192).decode(errors="replace")
        record["checkpoints"] = list(
            islice(
                (
                    str(path.relative_to(folder))
                    for path in folder.rglob("*")
                    if path.is_file() and path.suffix in {".pt", ".pth", ".ckpt", ".safetensors"}
                ),
                100,
            )
        )
        print("AXIOM_JOB=" + json.dumps(record, ensure_ascii=False))


if __name__ == "__main__":
    main()
