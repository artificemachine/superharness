from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from superharness.engine.state_errors import StateError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class FailureRow:
    id: int
    task_id: str | None
    agent: str | None
    pattern: str | None
    error_snippet: str | None
    created_at: str

def record(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    pattern: str | None = None,
    error_snippet: str | None = None,
    now: str,
) -> FailureRow:
    """Record a failure event.

    If task_id doesn't reference an existing task (e.g. synthetic identifiers
    like parallel-dispatch slot IDs — see engine/parallel_dispatch.py), the
    FK is degraded to NULL rather than losing the failure record entirely —
    matches the ON DELETE SET NULL semantics already used when a real task
    is later deleted.
    """
    try:
        return _insert(conn, task_id, agent, pattern, error_snippet, now)
    except sqlite3.IntegrityError as e:
        if task_id is None:
            raise StateError(f"Failed to record failure: {e}") from e
        logger.warning(
            "failures.task_id %r does not reference an existing task — recording with task_id=NULL",
            task_id,
        )
        return _insert(conn, None, agent, pattern, error_snippet, now)
    except sqlite3.Error as e:
        raise StateError(f"Failed to record failure: {e}") from e


def _insert(
    conn: sqlite3.Connection,
    task_id: str | None,
    agent: str | None,
    pattern: str | None,
    error_snippet: str | None,
    now: str,
) -> FailureRow:
    cursor = conn.execute(
        """
        INSERT INTO failures (task_id, agent, pattern, error_snippet, created_at)
        VALUES (?, ?, ?, ?, ?)
        RETURNING *
        """,
        (task_id, agent, pattern, error_snippet, now)
    )
    row = cursor.fetchone()
    if not row:
        raise StateError("Failed to record failure: no row returned")
    return _row_to_failure(row)

def get_recent(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    limit: int = 100,
) -> list[FailureRow]:
    """Get recent failure events."""
    query = "SELECT * FROM failures WHERE 1=1"
    params: list[Any] = []
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    
    cursor = conn.execute(query, params)
    return [_row_to_failure(row) for row in cursor.fetchall()]

def _row_to_failure(row: sqlite3.Row) -> FailureRow:
    return FailureRow(
        id=row["id"],
        task_id=row["task_id"],
        agent=row["agent"],
        pattern=row["pattern"],
        error_snippet=row["error_snippet"],
        created_at=row["created_at"]
    )
