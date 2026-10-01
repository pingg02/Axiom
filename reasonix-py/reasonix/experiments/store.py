"""Keep experiment metadata in the same user state database, never credentials."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


class ExperimentStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS experiments (
                    id TEXT PRIMARY KEY,
                    target TEXT NOT NULL,
                    directory TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def save(self, record: dict[str, Any]) -> None:
        record = {**record, "updated_at": time.time()}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO experiments (id, target, directory, payload, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload = excluded.payload,
                    updated_at = excluded.updated_at
            """,
                (
                    record["id"],
                    record["target"],
                    record["directory"],
                    json.dumps(record, ensure_ascii=False),
                    record["updated_at"],
                ),
            )

    def get(self, experiment_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM experiments WHERE id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Unknown experiment")
        result: dict[str, Any] = json.loads(row["payload"])
        return result

    def list(self, target: str = "", directory: str = "") -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM experiments WHERE target = ? AND directory = ? "
                "ORDER BY updated_at DESC LIMIT 100",
                (target, directory),
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]
