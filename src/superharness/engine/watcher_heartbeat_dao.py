"""DAO for richer heartbeat_contract.AgentHeartbeat records.

Backed by the extended `agent_heartbeats` table (migration v25 added
runtime, active_task, next_wake_at, written_at, tokens_used/limit, cost_usd).

This DAO is the SQLite source of truth for `heartbeat_contract.write_heartbeat`
and `read_heartbeat`. The YAML files at `.superharness/watcher.heartbeat.yaml`
and `.superharness/agents/<agent>.heartbeat.yaml` are export mirrors.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError


@dataclass(frozen=True)
class WatcherHeartbeatRow:
    agent_id: str
    schema_version: str
    runtime: str
    pid: int | None
    status: str
    active_task: str | None
    next_wake_at: str | None
    written_at: str
    tokens_used: int | None
    tokens_limit: int | None
    cost_usd: float | None
    updated_at: str


def upsert(
    conn: sqlite3.Connection,
    *,
    agent_id: str,
    schema_version: str = "1",
    runtime: str = "native",
    pid: int | None = None,
    status: str = "idle",
    active_task: str | None = None,
    next_wake_at: str | None = None,
    written_at: str,
    tokens_used: int | None = None,
    tokens_limit: int | None = None,
    cost_usd: float | None = None,
) -> WatcherHeartbeatRow:
    """Insert or update the heartbeat-contract record for an agent."""
    try:
        existing = conn.execute(
            "SELECT id FROM agent_heartbeats WHERE agent = ?", (agent_id,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE agent_heartbeats
                   SET runtime=?, pid=?, status=?, active_task=?, next_wake_at=?,
                       written_at=?, tokens_used=?, tokens_limit=?, cost_usd=?,
                       updated_at=?, task_id=?
                 WHERE agent=?
                """,
                (runtime, pid, status, active_task, next_wake_at,
                 written_at, tokens_used, tokens_limit, cost_usd,
                 written_at, active_task, agent_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO agent_heartbeats (
                    agent, task_id, status, pid, updated_at, created_at,
                    runtime, active_task, next_wake_at, written_at,
                    tokens_used, tokens_limit, cost_usd
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (agent_id, active_task, status, pid, written_at, written_at,
                 runtime, active_task, next_wake_at, written_at,
                 tokens_used, tokens_limit, cost_usd),
            )
        row = conn.execute(
            "SELECT * FROM agent_heartbeats WHERE agent = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise StateError("watcher_heartbeat upsert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"watcher_heartbeat upsert failed: {e}") from e


def get(conn: sqlite3.Connection, agent_id: str) -> WatcherHeartbeatRow | None:
    try:
        row = conn.execute(
            "SELECT * FROM agent_heartbeats WHERE agent = ?", (agent_id,)
        ).fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"watcher_heartbeat get failed: {e}") from e


def get_all(conn: sqlite3.Connection) -> list[WatcherHeartbeatRow]:
    """Return all heartbeat records ordered by most recently updated."""
    try:
        rows = conn.execute(
            "SELECT * FROM agent_heartbeats ORDER BY updated_at DESC"
        ).fetchall()
        return [_to_row(r) for r in rows]
    except sqlite3.Error as e:
        raise StateError(f"watcher_heartbeat get_all failed: {e}") from e


def _col(row: sqlite3.Row, name: str, default=None):
    try:
        v = row[name]
        return v if v is not None else default
    except (IndexError, KeyError):
        return default


def _to_row(row: sqlite3.Row) -> WatcherHeartbeatRow:
    written_at = _col(row, "written_at", "") or row["updated_at"]
    return WatcherHeartbeatRow(
        agent_id=row["agent"],
        schema_version=_col(row, "schema_version", "1"),
        runtime=_col(row, "runtime", "native"),
        pid=row["pid"],
        status=row["status"],
        active_task=_col(row, "active_task") or row["task_id"],
        next_wake_at=_col(row, "next_wake_at"),
        written_at=written_at,
        tokens_used=_col(row, "tokens_used"),
        tokens_limit=_col(row, "tokens_limit"),
        cost_usd=_col(row, "cost_usd"),
        updated_at=row["updated_at"],
    )
