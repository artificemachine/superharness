"""DAO for agent_pulses table.

Backs `shux agent-pulse write/read/clear`. The YAML file at
`.superharness/agent-pulse.yaml` is an export mirror.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError


@dataclass(frozen=True)
class AgentPulseRow:
    agent: str
    task_id: str
    status: str
    pid: int | None
    message: str | None
    last_seen: str


def upsert(
    conn: sqlite3.Connection,
    *,
    agent: str,
    task_id: str,
    status: str = "running",
    pid: int | None = None,
    message: str | None = None,
    last_seen: str,
) -> AgentPulseRow:
    try:
        conn.execute(
            """
            INSERT INTO agent_pulses (agent, task_id, status, pid, message, last_seen)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent) DO UPDATE SET
                task_id=excluded.task_id,
                status=excluded.status,
                pid=excluded.pid,
                message=excluded.message,
                last_seen=excluded.last_seen
            """,
            (agent, task_id, status, pid, message, last_seen),
        )
        row = conn.execute(
            "SELECT * FROM agent_pulses WHERE agent = ?", (agent,)
        ).fetchone()
        if not row:
            raise StateError("agent_pulse upsert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"agent_pulse upsert failed: {e}") from e


def get(conn: sqlite3.Connection, agent: str) -> AgentPulseRow | None:
    try:
        row = conn.execute(
            "SELECT * FROM agent_pulses WHERE agent = ?", (agent,)
        ).fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"agent_pulse get failed: {e}") from e


def get_latest(conn: sqlite3.Connection) -> AgentPulseRow | None:
    """Return the most recently active pulse across all agents (single-active model).

    Maps the legacy single-file `agent-pulse.yaml` semantics: only one agent
    is running at a time. If multiple rows exist, return the freshest.
    """
    try:
        row = conn.execute(
            "SELECT * FROM agent_pulses ORDER BY last_seen DESC LIMIT 1"
        ).fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"agent_pulse get_latest failed: {e}") from e


def delete(conn: sqlite3.Connection, agent: str) -> bool:
    try:
        cursor = conn.execute("DELETE FROM agent_pulses WHERE agent = ?", (agent,))
        return cursor.rowcount > 0
    except sqlite3.Error as e:
        raise StateError(f"agent_pulse delete failed: {e}") from e


def delete_all(conn: sqlite3.Connection) -> int:
    try:
        cursor = conn.execute("DELETE FROM agent_pulses")
        return cursor.rowcount
    except sqlite3.Error as e:
        raise StateError(f"agent_pulse delete_all failed: {e}") from e


def _to_row(row: sqlite3.Row) -> AgentPulseRow:
    return AgentPulseRow(
        agent=row["agent"],
        task_id=row["task_id"],
        status=row["status"],
        pid=row["pid"],
        message=row["message"],
        last_seen=row["last_seen"],
    )
