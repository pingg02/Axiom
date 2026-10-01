"""SQLite-backed durable conversation and crash-checkpoint storage."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from reasonix.diff import Change
from reasonix.provider import Message, Role, ToolCall


@dataclass(frozen=True)
class SessionRecord:
    id: str
    title: str
    workspace: str
    created_at: float
    updated_at: float
    status: str
    last_error: str = ""


@dataclass(frozen=True)
class ChangeRecord:
    session_id: str
    turn_id: str
    sequence: int
    path: str
    old_content: str | None
    new_content: str | None
    description: str
    reverted: bool
    created_at: float


@dataclass(frozen=True)
class WorkflowRecord:
    id: str
    workspace: str
    name: str
    steps: list[str]
    created_at: float
    updated_at: float


def default_history_path() -> Path:
    """Return the per-user desktop state database path."""
    override = os.environ.get("AXIOM_STATE_DIR", "")
    if override:
        root = Path(override).expanduser()
    elif os.name == "nt":
        root = Path(os.environ.get("APPDATA", "~/.config")).expanduser() / "axiom-desktop"
    else:
        root = (
            Path(os.environ.get("XDG_STATE_HOME", "~/.local/state")).expanduser() / "axiom-desktop"
        )
    return root / "state" / "axiom.db"


class SessionStore:
    """Persist sessions without storing provider credentials."""

    def __init__(self, path: str | Path, *, recover_running: bool = False) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()
        if recover_running:
            with self._lock, self._connect() as connection:
                connection.execute(
                    "UPDATE sessions SET status = 'interrupted' WHERE status = 'running'"
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    workspace TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS messages (
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (session_id, sequence),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS checkpoints (
                    session_id TEXT PRIMARY KEY,
                    pending_input TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS changes (
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    path TEXT NOT NULL,
                    old_content TEXT,
                    new_content TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    reverted INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    PRIMARY KEY (session_id, turn_id, sequence),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    workspace TEXT NOT NULL,
                    name TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tool_executions (
                    session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL,
                    call_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    args_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    output TEXT NOT NULL DEFAULT '',
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (session_id, turn_id, call_id),
                    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS subagent_runs (
                    child_id TEXT PRIMARY KEY,
                    parent_id TEXT NOT NULL,
                    parent_turn_id TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    FOREIGN KEY (child_id) REFERENCES sessions(id) ON DELETE CASCADE,
                    FOREIGN KEY (parent_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_workflows_workspace
                ON workflows(workspace, updated_at DESC);
                """
            )

    def create_session(
        self,
        session_id: str,
        *,
        title: str,
        workspace: str,
        created_at: float,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO sessions
                    (id, title, workspace, created_at, updated_at, status, last_error)
                VALUES (?, ?, ?, ?, ?, 'idle', '')
                """,
                (session_id, title, workspace, created_at, created_at),
            )

    def set_status(self, session_id: str, status: str, error: str = "") -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE sessions
                SET status = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, error, time.time(), session_id),
            )

    def set_title(self, session_id: str, title: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title, time.time(), session_id),
            )

    def save_messages(self, session_id: str, messages: list[Message]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            connection.executemany(
                "INSERT INTO messages (session_id, sequence, payload) VALUES (?, ?, ?)",
                [
                    (
                        session_id,
                        sequence,
                        json.dumps(_message_to_dict(message), ensure_ascii=False),
                    )
                    for sequence, message in enumerate(messages)
                ],
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (time.time(), session_id),
            )

    def load_messages(self, session_id: str) -> list[Message]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM messages WHERE session_id = ? ORDER BY sequence",
                (session_id,),
            ).fetchall()
        return [_message_from_dict(json.loads(row["payload"])) for row in rows]

    def record_tool(
        self,
        session_id: str,
        turn_id: str,
        call: ToolCall,
        state: str,
        output: str,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tool_executions
                    (session_id, turn_id, call_id, tool_name, args_json, state, output, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, turn_id, call_id) DO UPDATE SET
                    state = excluded.state, output = excluded.output,
                    updated_at = excluded.updated_at
                """,
                (
                    session_id,
                    turn_id,
                    call.id,
                    call.name,
                    call.args_json,
                    state,
                    output,
                    time.time(),
                ),
            )

    def tool_executions(self, session_id: str) -> list[dict[str, object]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY updated_at",
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def link_subagent(self, parent_id: str, turn_id: str, child_id: str, depth: int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO subagent_runs VALUES (?, ?, ?, ?)",
                (child_id, parent_id, turn_id, depth),
            )

    def subagent_runs(self, parent_id: str) -> list[dict[str, object]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM subagent_runs WHERE parent_id = ?",
                (parent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def reconcile_interrupted_tools(self, session_id: str) -> list[Message]:
        """Close missing tool responses without replaying any external action."""
        messages = self.load_messages(session_id)
        results = {str(row["call_id"]): row for row in self.tool_executions(session_id)}
        reconciled: list[Message] = []
        for index, message in enumerate(messages):
            reconciled.append(message)
            if not message.tool_calls:
                continue
            following = messages[index + 1 :]
            responded = set()
            for response in following:
                if response.role != Role.TOOL:
                    break
                responded.add(response.tool_call_id)
            for call in message.tool_calls:
                if call.id in responded:
                    continue
                result = results.get(call.id)
                output = (
                    str(result["output"])
                    if result and result["state"] == "completed"
                    else "Error: interrupted tool call; outcome is unknown. Do not automatically "
                    "retry this action. Inspect files/job records and ask the user first."
                )
                reconciled.append(
                    Message(
                        role=Role.TOOL,
                        tool_call_id=call.id,
                        name=call.name,
                        content=output,
                    )
                )
        self.save_messages(session_id, reconciled)
        return reconciled

    def save_checkpoint(
        self,
        session_id: str,
        pending_input: str,
        history: list[Message],
    ) -> None:
        history_json = json.dumps(
            [_message_to_dict(message) for message in history],
            ensure_ascii=False,
        )
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints
                    (session_id, pending_input, history_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    pending_input = excluded.pending_input,
                    history_json = excluded.history_json,
                    created_at = excluded.created_at
                """,
                (session_id, pending_input, history_json, time.time()),
            )
            connection.execute(
                """
                UPDATE sessions SET status = 'running', updated_at = ?
                WHERE id = ?
                """,
                (time.time(), session_id),
            )

    def clear_checkpoint(self, session_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM checkpoints WHERE session_id = ?", (session_id,))

    def checkpoint_prompt(self, session_id: str) -> str:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT pending_input FROM checkpoints WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return str(row["pending_input"]) if row else ""

    def record_change(self, session_id: str, turn_id: str, change: Change) -> None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence
                FROM changes WHERE session_id = ? AND turn_id = ?
                """,
                (session_id, turn_id),
            ).fetchone()
            sequence = int(row["next_sequence"])
            connection.execute(
                """
                INSERT INTO changes (
                    session_id, turn_id, sequence, path, old_content,
                    new_content, description, reverted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    session_id,
                    turn_id,
                    sequence,
                    change.path,
                    change.old_content,
                    change.new_content,
                    change.description,
                    time.time(),
                ),
            )

    def latest_changes(self, session_id: str) -> list[ChangeRecord]:
        with self._lock, self._connect() as connection:
            turn_row = connection.execute(
                """
                SELECT turn_id FROM changes
                WHERE session_id = ? AND reverted = 0
                ORDER BY created_at DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if not turn_row:
                return []
            rows = connection.execute(
                """
                SELECT session_id, turn_id, sequence, path, old_content,
                       new_content, description, reverted, created_at
                FROM changes
                WHERE session_id = ? AND turn_id = ?
                ORDER BY sequence
                """,
                (session_id, turn_row["turn_id"]),
            ).fetchall()
        return [ChangeRecord(**{**dict(row), "reverted": bool(row["reverted"])}) for row in rows]

    def mark_turn_reverted(self, session_id: str, turn_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE changes SET reverted = 1
                WHERE session_id = ? AND turn_id = ?
                """,
                (session_id, turn_id),
            )

    def save_workflow(
        self,
        workflow_id: str,
        *,
        workspace: str,
        name: str,
        steps: list[str],
    ) -> None:
        now = time.time()
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO workflows
                    (id, workspace, name, steps_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    workspace = excluded.workspace,
                    name = excluded.name,
                    steps_json = excluded.steps_json,
                    updated_at = excluded.updated_at
                """,
                (
                    workflow_id,
                    workspace,
                    name,
                    json.dumps(steps, ensure_ascii=False),
                    now,
                    now,
                ),
            )

    def list_workflows(self, workspace: str) -> list[WorkflowRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, workspace, name, steps_json, created_at, updated_at
                FROM workflows
                WHERE workspace = ?
                ORDER BY updated_at DESC
                """,
                (workspace,),
            ).fetchall()
        return [
            WorkflowRecord(
                id=str(row["id"]),
                workspace=str(row["workspace"]),
                name=str(row["name"]),
                steps=[
                    str(step) for step in json.loads(str(row["steps_json"])) if str(step).strip()
                ],
                created_at=float(row["created_at"]),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        ]

    def delete_workflow(self, workflow_id: str, workspace: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM workflows WHERE id = ? AND workspace = ?",
                (workflow_id, workspace),
            )
        return cursor.rowcount > 0

    def list_sessions(self, limit: int = 100) -> list[SessionRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, title, workspace, created_at, updated_at, status, last_error
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [SessionRecord(**dict(row)) for row in rows]

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, title, workspace, created_at, updated_at, status, last_error
                FROM sessions WHERE id = ?
                """,
                (session_id,),
            ).fetchone()
        return SessionRecord(**dict(row)) if row else None

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0


def _message_to_dict(message: Message) -> dict[str, object]:
    data = asdict(message)
    data["role"] = message.role.value
    return data


def _message_from_dict(data: dict[str, object]) -> Message:
    raw_calls = data.get("tool_calls", [])
    raw_images = data.get("images", [])
    raw_duration = data.get("work_duration_ms", 0)
    tool_calls = (
        [
            ToolCall(
                id=str(call.get("id", "")),
                name=str(call.get("name", "")),
                args_json=str(call.get("args_json", "")),
            )
            for call in raw_calls
            if isinstance(call, dict)
        ]
        if isinstance(raw_calls, list)
        else []
    )
    return Message(
        role=Role(str(data.get("role", Role.USER.value))),
        content=str(data.get("content", "")),
        images=[str(value) for value in raw_images] if isinstance(raw_images, list) else [],
        reasoning_content=str(data.get("reasoning_content", "")),
        reasoning_signature=str(data.get("reasoning_signature", "")),
        tool_calls=tool_calls,
        tool_call_id=str(data.get("tool_call_id", "")),
        name=str(data.get("name", "")),
        work_duration_ms=raw_duration if isinstance(raw_duration, int) else 0,
        edited=bool(data.get("edited", False)),
        original=str(data.get("original", "")),
    )
