"""Penyimpanan status job di SQLite (cukup untuk demo, gampang di-reset di test)."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    s3_key TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""

STATUSES = ("queued", "processing", "done", "failed")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class JobStore:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def create(self, filename: str) -> dict:
        job_id = uuid.uuid4().hex[:12]
        now = _now()
        self.conn.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, 'queued', NULL, NULL, ?, ?)",
            (job_id, filename, f"uploads/{job_id}.csv", now, now),
        )
        self.conn.commit()
        return self.get(job_id)

    def update(self, job_id: str, status: str, result: dict | None = None,
               error: str | None = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"status tidak dikenal: {status}")
        self.conn.execute(
            "UPDATE jobs SET status=?, result=?, error=?, updated_at=? WHERE id=?",
            (status, json.dumps(result) if result else None, error, _now(), job_id),
        )
        self.conn.commit()

    def get(self, job_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._to_dict(row) if row else None

    def list(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        data = dict(row)
        data["result"] = json.loads(data["result"]) if data["result"] else None
        return data
