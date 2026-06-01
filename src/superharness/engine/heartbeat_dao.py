"""DAO for agent_heartbeats table.

Agents call `shux heartbeat` every 30s to register liveness.
The watcher reconciler marks rows stale when updated_at is >2 minutes old.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError

STALE_THRESHOLD_SECONDS = 120


@dataclass(frozen=True)
class HeartbeatRow:
    id: int
    agent: str
    task_id: str | None
    status: str
    pid: int | None
    updated_at: str
    created_at: str
    runtime: str | None = None
    active_task: str | None = None
    next_wake_at: str | None = None
    written_at: str | None = None
    tokens_used: int | None = None
    tokens_limit: int | None = None
    cost_usd: float | None = None


def upsert(
    conn: sqlite3.Connection,
    *,
    agent: str,
    task_id: str | None = None,
    status: str = "alive",
    pid: int | None = None,
    now: str,
    runtime: str | None = None,
    active_task: str | None = None,
    next_wake_at: str | None = None,
    tokens_used: int | None = None,
    tokens_limit: int | None = None,
    cost_usd: float | None = None,
) -> HeartbeatRow:
    """Insert or update the heartbeat row for an agent."""
    try:
        existing = conn.execute(
            "SELECT id FROM agent_heartbeats WHERE agent = ?", (agent,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE agent_heartbeats 
                SET task_id=?, status=?, pid=?, updated_at=?, 
                    runtime=?, active_task=?, next_wake_at=?, written_at=?,
                    tokens_used=?, tokens_limit=?, cost_usd=?
                WHERE agent=?
                """,
                (task_id, status, pid, now, 
                 runtime, active_task, next_wake_at, now,
                 tokens_used, tokens_limit, cost_usd, agent),
            )
            row = conn.execute(
                "SELECT * FROM agent_heartbeats WHERE agent = ?",
                (agent,),
            ).fetchone()
        else:
            cursor = conn.execute(
                """
                INSERT INTO agent_heartbeats 
                (agent, task_id, status, pid, updated_at, created_at,
                 runtime, active_task, next_wake_at, written_at,
                 tokens_used, tokens_limit, cost_usd) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (agent, task_id, status, pid, now, now,
                 runtime, active_task, next_wake_at, now,
                 tokens_used, tokens_limit, cost_usd),
            )
            row = conn.execute(
                "SELECT * FROM agent_heartbeats WHERE id = last_insert_rowid()"
            ).fetchone()
        if not row:
            raise StateError("heartbeat upsert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"heartbeat upsert failed: {e}") from e


def get_all(conn: sqlite3.Connection) -> list[HeartbeatRow]:
    """Return all heartbeat rows ordered by most recently updated."""
    try:
        rows = conn.execute(
            "SELECT * FROM agent_heartbeats ORDER BY updated_at DESC"
        ).fetchall()
        return [_to_row(r) for r in rows]
    except sqlite3.Error as e:
        raise StateError(f"heartbeat get_all failed: {e}") from e


def get(conn: sqlite3.Connection, agent: str) -> HeartbeatRow | None:
    """Return the heartbeat row for a specific agent, or None."""
    try:
        row = conn.execute(
            "SELECT * FROM agent_heartbeats WHERE agent = ?",
            (agent,),
        ).fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"heartbeat get failed: {e}") from e


def mark_stale(conn: sqlite3.Connection, *, now: str) -> int:
    """Mark as zombie any heartbeat not updated in the last STALE_THRESHOLD_SECONDS.

    Returns the number of rows updated.
    """
    try:
        cursor = conn.execute(
            """
            UPDATE agent_heartbeats
            SET status = 'zombie'
            WHERE status = 'alive'
              AND (
                CAST(strftime('%s', ?) AS INTEGER) -
                CAST(strftime('%s', updated_at) AS INTEGER)
              ) > ?
            """,
            (now, STALE_THRESHOLD_SECONDS),
        )
        return cursor.rowcount
    except sqlite3.Error as e:
        raise StateError(f"heartbeat mark_stale failed: {e}") from e


def _to_row(row: sqlite3.Row) -> HeartbeatRow:
    return HeartbeatRow(
        id=row["id"],
        agent=row["agent"],
        task_id=row["task_id"],
        status=row["status"],
        pid=row["pid"],
        updated_at=row["updated_at"],
        created_at=row["created_at"],
        runtime=row["runtime"] if "runtime" in row.keys() else None,
        active_task=row["active_task"] if "active_task" in row.keys() else None,
        next_wake_at=row["next_wake_at"] if "next_wake_at" in row.keys() else None,
        written_at=row["written_at"] if "written_at" in row.keys() else None,
        tokens_used=row["tokens_used"] if "tokens_used" in row.keys() else None,
        tokens_limit=row["tokens_limit"] if "tokens_limit" in row.keys() else None,
        cost_usd=row["cost_usd"] if "cost_usd" in row.keys() else None,
    )
