from __future__ import annotations

import sqlite3
import json
from dataclasses import dataclass
from typing import Any, cast

from superharness.engine.state_errors import StateError

@dataclass(frozen=True)
class InboxRow:
    id: str
    task_id: str
    target_agent: str
    status: str
    priority: int
    retry_count: int
    max_retries: int
    recovery_count: int
    pid: int | None
    project_path: str | None
    plan_only: bool
    failed_reason: str | None
    created_at: str
    launched_at: str | None
    last_heartbeat: str | None
    paused_at: str | None
    failed_at: str | None
    done_at: str | None

_ACTIVE_STATUSES = ("pending", "launched", "running", "paused")


def enqueue(
    conn: sqlite3.Connection,
    *,
    id: str,
    task_id: str,
    target_agent: str,
    priority: int = 2,
    max_retries: int = 3,
    project_path: str | None = None,
    plan_only: bool = False,
    model_override: str = "",
    now: str,
) -> InboxRow:
    """Insert a new inbox row with status='pending'.

    Raises StateError if an active row already exists for (task_id, target_agent)
    to mirror the dedup guard on the YAML side.
    """
    placeholders = ",".join("?" * len(_ACTIVE_STATUSES))
    existing = conn.execute(
        f"SELECT id FROM inbox WHERE task_id=? AND target_agent=? AND status IN ({placeholders}) LIMIT 1",
        (task_id, target_agent, *_ACTIVE_STATUSES),
    ).fetchone()
    if existing:
        raise StateError(
            f"Duplicate rejected: active inbox row already exists for task '{task_id}' "
            f"→ '{target_agent}' (id={existing['id']})"
        )
    try:
        cursor = conn.execute(
            """
            INSERT INTO inbox (
                id, task_id, target_agent, status, priority, max_retries,
                project_path, plan_only, created_at
            ) VALUES (?, ?, ?, 'pending', ?, ?, ?, ?, ?)
            RETURNING *
            """,
            (id, task_id, target_agent, priority, max_retries, project_path, 1 if plan_only else 0, now)
        )
        row = cursor.fetchone()
        if not row:
            raise StateError("Failed to enqueue inbox item: no row returned")
        return _row_to_inbox(row)
    except sqlite3.IntegrityError as e:
        raise StateError(f"Failed to enqueue inbox item '{id}': {e}") from e
    except sqlite3.Error as e:
        raise StateError(f"Database error during enqueue: {e}") from e

def get(conn: sqlite3.Connection, id: str) -> InboxRow | None:
    """Get a single inbox row by ID."""
    cursor = conn.execute("SELECT * FROM inbox WHERE id = ?", (id,))
    row = cursor.fetchone()
    return _row_to_inbox(row) if row else None

def get_all(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    target_agent: str | None = None,
    limit: int | None = None,
) -> list[InboxRow]:
    """Get multiple inbox rows, ordered by priority DESC, created_at ASC."""
    query = "SELECT * FROM inbox WHERE 1=1"
    params: list[Any] = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if target_agent:
        query += " AND target_agent = ?"
        params.append(target_agent)
    
    query += " ORDER BY priority DESC, created_at ASC"
    if limit:
        query += " LIMIT ?"
        params.append(limit)
        
    cursor = conn.execute(query, params)
    return [_row_to_inbox(row) for row in cursor.fetchall()]

def claim_next(
    conn: sqlite3.Connection,
    *,
    target_agent: str,
    pid: int,
    now: str,
) -> InboxRow | None:
    """Atomically claim the next pending inbox item for an agent.
    
    Uses a single atomic UPDATE with subquery. Safe for concurrent watchers:
    SQLite serializes writes; only one claimer per pending item.
    """
    try:
        # Ensure serialized write access for concurrent watchers
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        # Atomic claim pattern
        cursor = conn.execute(
            """
            UPDATE inbox
            SET status='launched', pid=?, launched_at=?, last_heartbeat=?
            WHERE id = (
                SELECT id FROM inbox
                WHERE status='pending' AND target_agent=?
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
            )
            RETURNING *
            """,
            (pid, now, now, target_agent)
        )
        row = cursor.fetchone()
        return _row_to_inbox(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"Failed to claim next task for agent '{target_agent}': {e}") from e

def update_status(
    conn: sqlite3.Connection,
    id: str,
    *,
    from_status: str,
    to_status: str,
    now: str,
    reason: str | None = None,
) -> bool:
    """Transition a row status atomically if current status matches from_status."""
    query = "UPDATE inbox SET status = ?"
    params: list[Any] = [to_status]
    if to_status == "done":
        query += ", done_at = ?"
        params.append(now)
    elif to_status == "failed":
        query += ", failed_at = ?, failed_reason = ?"
        params.extend([now, reason])
    elif to_status == "paused":
        query += ", paused_at = ?"
        params.append(now)
        
    query += " WHERE id = ? AND status = ?"
    params.extend([id, from_status])
    
    cursor = conn.execute(query, params)
    return cursor.rowcount > 0

def mark_heartbeat(conn: sqlite3.Connection, id: str, now: str) -> None:
    """Update last_heartbeat for an inbox item."""
    conn.execute("UPDATE inbox SET last_heartbeat = ? WHERE id = ?", (now, id))

def get_stale(
    conn: sqlite3.Connection,
    *,
    timeout_seconds: int,
    now: str,
) -> list[InboxRow]:
    """Get rows where status is launched/running and last_heartbeat is too old."""
    # Compute cutoff in Python; SQLite datetime() does not accept the 'Z' suffix.
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    cutoff = (
        _dt.strptime(now.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
        .replace(tzinfo=_tz.utc) - _td(seconds=timeout_seconds)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    cursor = conn.execute(
        """
        SELECT * FROM inbox
        WHERE status IN ('launched', 'running')
          AND last_heartbeat < ?
        """,
        (cutoff,),
    )
    return [_row_to_inbox(row) for row in cursor.fetchall()]

def set_retry(
    conn: sqlite3.Connection,
    id: str,
    retry_count: int,
    failed_reason: str | None,
    now: str,
) -> None:
    """Update retry count and reason for an inbox item."""
    conn.execute(
        """
        UPDATE inbox 
        SET retry_count = ?, failed_reason = ?, status = 'pending', pid = NULL
        WHERE id = ?
        """,
        (retry_count, failed_reason, id)
    )

def _row_to_inbox(row: sqlite3.Row) -> InboxRow:
    return InboxRow(
        id=row["id"],
        task_id=row["task_id"],
        target_agent=row["target_agent"],
        status=row["status"],
        priority=row["priority"],
        retry_count=row["retry_count"],
        max_retries=row["max_retries"],
        recovery_count=row["recovery_count"] if "recovery_count" in row.keys() else 0,
        pid=row["pid"],
        project_path=row["project_path"],
        plan_only=bool(row["plan_only"]),
        failed_reason=row["failed_reason"],
        created_at=row["created_at"],
        launched_at=row["launched_at"],
        last_heartbeat=row["last_heartbeat"],
        paused_at=row["paused_at"],
        failed_at=row["failed_at"],
        done_at=row["done_at"]
    )
