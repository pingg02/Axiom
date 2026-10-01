"""Explicit user job commands over OpenCode's user-shell API (no LLM required)."""

from __future__ import annotations

import base64
import json
import shlex
import uuid
from pathlib import Path
from typing import Any

from reasonix.remote.client import OpenCodeClient, RemoteError

from .store import ExperimentStore


class ExperimentService:
    def __init__(self, client: OpenCodeClient, store: ExperimentStore) -> None:
        self.client = client
        self.store = store

    async def submit(
        self,
        session_id: str,
        name: str,
        command: str,
        config_path: str = "",
    ) -> dict[str, Any]:
        if not name.strip() or not command.strip() or len(command) > 16000:
            raise ValueError("Experiment needs a name and a command (at most 16000 characters)")
        record = {
            "id": "exp_" + uuid.uuid4().hex,
            "name": name.strip(),
            "command": command,
            "config_path": config_path,
            "target": self.client.config.url.rstrip("/"),
            "directory": self.client.config.directory,
            "session_id": session_id,
            "state": "submitting",
            "metrics": {},
        }
        self.store.save(record)
        try:
            return await self._execute(record, "submit")
        except (RemoteError, ValueError):
            # A lost acknowledgement may still mean the job started. Never submit
            # it again automatically: the durable ID lets the user query it.
            self.store.save({**record, "state": "unknown"})
            raise

    async def refresh(self, experiment_id: str, *, stop: bool = False) -> dict[str, Any]:
        record = self.store.get(experiment_id)
        if (
            record["target"] != self.client.config.url.rstrip("/")
            or record["directory"] != self.client.config.directory
        ):
            raise ValueError("Reconnect to this experiment's original server and directory")
        return await self._execute(record, "stop" if stop else "status")

    async def _execute(self, record: dict[str, Any], action: str) -> dict[str, Any]:
        code = (Path(__file__).parent / "worker.py").read_bytes()
        source = base64.b64encode(code).decode()
        launcher = "import base64;exec(base64.b64decode(" + repr(source) + "))"
        payload = json.dumps(
            {
                key: record[key]
                for key in (
                    "id",
                    "name",
                    "command",
                    "config_path",
                    "directory",
                )
            },
            ensure_ascii=False,
        )
        command = "python3 -c " + shlex.quote(launcher) + " " + shlex.quote(payload)
        command += " " + shlex.quote(source) + " " + shlex.quote(action)
        response = await self.client.request(
            "POST",
            self.client.session_path(str(record["session_id"]), "/shell"),
            {"agent": "build", "command": command},
        )
        output = "\n".join(
            str(part.get("state", {}).get("output", ""))
            for part in response.get("parts", [])
            if part.get("type") == "tool"
        )
        lines = [line for line in output.splitlines() if line.startswith("AXIOM_JOB=")]
        if not lines:
            raise RemoteError("Remote job command failed; inspect the OpenCode shell output")
        result = json.loads(lines[-1].removeprefix("AXIOM_JOB="))
        if result.get("id") != record["id"]:
            raise RemoteError("Remote job identity mismatch")
        updated = {**record, **result}
        # Transport identity is local metadata, not trusted remote output.
        updated.update(
            target=record["target"],
            session_id=record["session_id"],
            directory=record["directory"],
            resolved_directory=result.get("directory", ""),
        )
        self.store.save(updated)
        return updated
