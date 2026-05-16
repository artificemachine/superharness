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


def upsert(
    conn: sqlite3.Connection,
    *,
    agent: str,
    task_id: str | None = None,
    status: str = "alive",
    pid: int | None = None,
    now: str,
) -> HeartbeatRow:
    """Insert or update the heartbeat row for an agent."""
    try:
        existing = conn.execute(
            "SELECT id FROM agent_heartbeats WHERE agent = ?", (agent,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE agent_heartbeats SET task_id=?, status=?, pid=?, updated_at=? WHERE agent=?",
                (task_id, status, pid, now, agent),
            )
            row = conn.execute(
                "SELECT id, agent, task_id, status, pid, updated_at, created_at "
                "FROM agent_heartbeats WHERE agent = ?",
                (agent,),
            ).fetchone()
        else:
            cursor = conn.execute(
                "INSERT INTO agent_heartbeats (agent, task_id, status, pid, updated_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) RETURNING id, agent, task_id, status, pid, updated_at, created_at",
                (agent, task_id, status, pid, now, now),
            )
            row = cursor.fetchone()
        if not row:
            raise StateError("heartbeat upsert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"heartbeat upsert failed: {e}") from e


def get_all(conn: sqlite3.Connection) -> list[HeartbeatRow]:
    """Return all heartbeat rows ordered by most recently updated."""
    try:
        rows = conn.execute(
            "SELECT id, agent, task_id, status, pid, updated_at, created_at "
            "FROM agent_heartbeats ORDER BY updated_at DESC"
        ).fetchall()
        return [_to_row(r) for r in rows]
    except sqlite3.Error as e:
        raise StateError(f"heartbeat get_all failed: {e}") from e


def get(conn: sqlite3.Connection, agent: str) -> HeartbeatRow | None:
    """Return the heartbeat row for a specific agent, or None."""
    try:
        row = conn.execute(
            "SELECT id, agent, task_id, status, pid, updated_at, created_at "
            "FROM agent_heartbeats WHERE agent = ?",
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
    )
