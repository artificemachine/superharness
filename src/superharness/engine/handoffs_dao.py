from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from typing import Any, cast

from superharness.engine.state_errors import StateError

@dataclass(frozen=True)
class HandoffRow:
    id: int
    task_id: str
    phase: str
    status: str
    from_agent: str | None
    to_agent: str | None
    content: str | None
    metadata: dict[str, Any]
    created_at: str

def append(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    phase: str,
    status: str,
    from_agent: str | None = None,
    to_agent: str | None = None,
    content: str | None = None,
    metadata: dict[str, Any] | None = None,
    now: str,
) -> HandoffRow:
    """Append a handoff event. Append-only: never updates or deletes."""
    meta_json = json.dumps(metadata or {})
    try:
        cursor = conn.execute(
            """
            INSERT INTO handoffs (
                task_id, phase, status, from_agent, to_agent, content, metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING *
            """,
            (task_id, phase, status, from_agent, to_agent, content, meta_json, now)
        )
        row = cursor.fetchone()
        if not row:
            raise StateError("Failed to append handoff: no row returned")
        return _row_to_handoff(row)
    except sqlite3.Error as e:
        raise StateError(f"Failed to append handoff for task '{task_id}': {e}") from e

def get_history(
    conn: sqlite3.Connection,
    task_id: str,
) -> list[HandoffRow]:
    """Return all handoffs for a task, ordered by created_at ASC."""
    cursor = conn.execute(
        "SELECT * FROM handoffs WHERE task_id = ? ORDER BY created_at ASC, id ASC",
        (task_id,)
    )
    return [_row_to_handoff(row) for row in cursor.fetchall()]

def get_all(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[HandoffRow]:
    """Return all handoffs, newest first. Optional row limit."""
    sql = "SELECT * FROM handoffs ORDER BY created_at DESC, id DESC"
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (int(limit),)
    cursor = conn.execute(sql, params)
    return [_row_to_handoff(row) for row in cursor.fetchall()]

def get_for_agent(
    conn: sqlite3.Connection,
    to_agent: str,
) -> list[HandoffRow]:
    """Return handoffs addressed to a given agent, newest first."""
    cursor = conn.execute(
        "SELECT * FROM handoffs WHERE to_agent = ? ORDER BY created_at DESC, id DESC",
        (to_agent,)
    )
    return [_row_to_handoff(row) for row in cursor.fetchall()]

def search(
    conn: sqlite3.Connection,
    term: str,
) -> list[HandoffRow]:
    """Substring search over handoff content and metadata, newest first."""
    like = f"%{term}%"
    cursor = conn.execute(
        "SELECT * FROM handoffs WHERE content LIKE ? OR metadata LIKE ? "
        "ORDER BY created_at DESC, id DESC",
        (like, like)
    )
    return [_row_to_handoff(row) for row in cursor.fetchall()]

def get_latest(
    conn: sqlite3.Connection,
    task_id: str,
    phase: str,
) -> HandoffRow | None:
    """Return the most recent handoff of the given phase for this task."""
    cursor = conn.execute(
        "SELECT * FROM handoffs WHERE task_id = ? AND phase = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (task_id, phase)
    )
    row = cursor.fetchone()
    return _row_to_handoff(row) if row else None

def _row_to_handoff(row: sqlite3.Row) -> HandoffRow:
    metadata_raw = row["metadata"]
    try:
        metadata = json.loads(metadata_raw) if metadata_raw else {}
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    return HandoffRow(
        id=row["id"],
        task_id=row["task_id"],
        phase=row["phase"],
        status=row["status"],
        from_agent=row["from_agent"],
        to_agent=row["to_agent"],
        content=row["content"],
        metadata=metadata,
        created_at=row["created_at"]
    )
