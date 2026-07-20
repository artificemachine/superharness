from __future__ import annotations

import logging
import sqlite3
import json
from dataclasses import dataclass
from typing import Any, cast

from superharness.engine.state_errors import StateError

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class DecisionRow:
    id: int
    agent: str | None
    task_id: str | None
    decision: str
    reason: str | None
    alternatives: list[str]
    created_at: str

def record(
    conn: sqlite3.Connection,
    *,
    agent: str | None = None,
    task_id: str | None = None,
    decision: str,
    reason: str | None = None,
    alternatives: list[str] | None = None,
    now: str,
) -> DecisionRow:
    """Record a decision event.

    If task_id doesn't reference an existing task, the FK is degraded to
    NULL rather than losing the decision record entirely — matches the
    ON DELETE SET NULL semantics already used when a real task is later
    deleted.
    """
    alt_json = json.dumps(alternatives or [])
    try:
        return _insert(conn, agent, task_id, decision, reason, alt_json, now)
    except sqlite3.IntegrityError as e:
        if task_id is None:
            raise StateError(f"Failed to record decision: {e}") from e
        logger.warning(
            "decisions.task_id %r does not reference an existing task — recording with task_id=NULL",
            task_id,
        )
        return _insert(conn, agent, None, decision, reason, alt_json, now)
    except sqlite3.Error as e:
        raise StateError(f"Failed to record decision: {e}") from e


def _insert(
    conn: sqlite3.Connection,
    agent: str | None,
    task_id: str | None,
    decision: str,
    reason: str | None,
    alt_json: str,
    now: str,
) -> DecisionRow:
    cursor = conn.execute(
        """
        INSERT INTO decisions (agent, task_id, decision, reason, alternatives, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING *
        """,
        (agent, task_id, decision, reason, alt_json, now)
    )
    row = cursor.fetchone()
    if not row:
        raise StateError("Failed to record decision: no row returned")
    return _row_to_decision(row)

def get_recent(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    limit: int = 100,
) -> list[DecisionRow]:
    """Get recent decision events."""
    query = "SELECT * FROM decisions WHERE 1=1"
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
    return [_row_to_decision(row) for row in cursor.fetchall()]

def _row_to_decision(row: sqlite3.Row) -> DecisionRow:
    return DecisionRow(
        id=row["id"],
        agent=row["agent"],
        task_id=row["task_id"],
        decision=row["decision"],
        reason=row["reason"],
        alternatives=json.loads(row["alternatives"]),
        created_at=row["created_at"]
    )
