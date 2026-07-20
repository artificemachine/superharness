from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from typing import Any, cast

from superharness.engine.state_errors import StateError

import logging
logger = logging.getLogger(__name__)

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
    """Record an operational trace entry.

    If task_id doesn't reference an existing task, the FK is degraded to
    NULL rather than losing the ledger record entirely — matches the
    ON DELETE SET NULL semantics already used when a real task is later
    deleted.
    """
    details_json = json.dumps(details) if details is not None else None

    try:
        return _insert(conn, task_id, agent, action, details_json, now)
    except sqlite3.IntegrityError as e:
        if task_id is None:
            raise StateError(f"Failed to record ledger entry: {e}") from e
        logger.warning(
            "ledger.task_id %r does not reference an existing task — recording with task_id=NULL",
            task_id,
        )
        return _insert(conn, None, agent, action, details_json, now)
    except sqlite3.Error as e:
        raise StateError(f"Failed to record ledger entry: {e}") from e


def _insert(
    conn: sqlite3.Connection,
    task_id: str | None,
    agent: str | None,
    action: str,
    details_json: str | None,
    now: str,
) -> LedgerRow:
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


def decision_log(
    project_dir: str,
    action: str,
    *,
    task_id: str | None = None,
    agent: str = "watcher",
    reason: str = "",
    details: dict[str, Any] | None = None,
) -> None:
    """Fire-and-forget decision recording. Never raises.

    Wraps ledger_dao.record() with automatic connection lifecycle.
    Use this at every decision point — gate blocks, auto-retries,
    escalations, cancellations, failures.
    """
    try:
        from superharness.engine.db import get_connection, init_db

        conn = get_connection(project_dir)
        try:
            init_db(conn)
            payload: dict[str, Any] = {"reason": reason}
            if details:
                payload.update(details)
            record(
                conn,
                task_id=task_id,
                agent=agent,
                action=action,
                details=payload,
                now=_now_utc(),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.warning("ledger_dao.py unexpected error: %s", e, exc_info=True)
        pass
def _now_utc() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
