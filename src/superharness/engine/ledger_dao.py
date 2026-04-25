from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from typing import Any, cast

from superharness.engine.state_errors import StateError

@dataclass(frozen=True)
class LedgerRow:
    id: int
    task_id: str | None
    agent: str | None
    action: str
    details: dict[str, Any] | None
    created_at: str

def record(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    action: str,
    details: dict[str, Any] | None = None,
    now: str,
) -> LedgerRow:
    """Record an operational trace entry."""
    details_json = json.dumps(details) if details is not None else None
    
    try:
        cursor = conn.execute(
            """
            INSERT INTO ledger (task_id, agent, action, details, created_at)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id, task_id, agent, action, details, created_at
            """,
            (task_id, agent, action, details_json, now)
        )
        row = cursor.fetchone()
        if not row:
            raise StateError("Failed to record ledger entry: no row returned")
        return _row_to_ledger(row)
    except sqlite3.Error as e:
        raise StateError(f"Failed to record ledger entry: {e}") from e

def get_recent(
    conn: sqlite3.Connection,
    *,
    task_id: str | None = None,
    agent: str | None = None,
    limit: int = 100,
) -> list[LedgerRow]:
    """Get recent ledger entries."""
    query = "SELECT id, task_id, agent, action, details, created_at FROM ledger WHERE 1=1"
    params: list[Any] = []
    if task_id:
        query += " AND task_id = ?"
        params.append(task_id)
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    
    try:
        cursor = conn.execute(query, params)
        return [_row_to_ledger(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        raise StateError(f"Failed to get recent ledger entries: {e}") from e

def _row_to_ledger(row: sqlite3.Row) -> LedgerRow:
    details = json.loads(row["details"]) if row["details"] else None
    return LedgerRow(
        id=row["id"],
        task_id=row["task_id"],
        agent=row["agent"],
        action=row["action"],
        details=cast("dict[str, Any] | None", details),
        created_at=row["created_at"]
    )
