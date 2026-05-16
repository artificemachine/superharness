"""DAO for task_artifacts table.

Agents register file outputs linked to a task. Each artifact has a type
(code|image|test_report|binary|file), optional hash, and file size.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError

VALID_TYPES = frozenset({"code", "image", "test_report", "binary", "file"})


@dataclass(frozen=True)
class ArtifactRow:
    id: int
    task_id: str
    agent: str | None
    path: str
    type: str
    hash: str | None
    size_bytes: int | None
    created_at: str


def add(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    path: str,
    agent: str | None = None,
    type: str = "file",
    hash: str | None = None,
    size_bytes: int | None = None,
    now: str,
) -> ArtifactRow:
    """Record a new artifact for a task."""
    artifact_type = type if type in VALID_TYPES else "file"
    try:
        cursor = conn.execute(
            """
            INSERT INTO task_artifacts (task_id, agent, path, type, hash, size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id, task_id, agent, path, type, hash, size_bytes, created_at
            """,
            (task_id, agent, path, artifact_type, hash, size_bytes, now),
        )
        row = cursor.fetchone()
        if not row:
            raise StateError("artifact insert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"artifact add failed: {e}") from e


def get_for_task(conn: sqlite3.Connection, task_id: str) -> list[ArtifactRow]:
    """Return all artifacts for a task, oldest first."""
    try:
        rows = conn.execute(
            "SELECT id, task_id, agent, path, type, hash, size_bytes, created_at "
            "FROM task_artifacts WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,),
        ).fetchall()
        return [_to_row(r) for r in rows]
    except sqlite3.Error as e:
        raise StateError(f"artifact get_for_task failed: {e}") from e


def _to_row(row: sqlite3.Row) -> ArtifactRow:
    return ArtifactRow(
        id=row["id"],
        task_id=row["task_id"],
        agent=row["agent"],
        path=row["path"],
        type=row["type"],
        hash=row["hash"],
        size_bytes=row["size_bytes"],
        created_at=row["created_at"],
    )
