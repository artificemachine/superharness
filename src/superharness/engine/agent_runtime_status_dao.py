"""DAO for agent_runtime_status table.

Backs `agent_status.write_agent_status` / `read_agent_status` / `read_all_agent_statuses`.
The YAML files at `.superharness/agents/<runtime>.status.yaml` are export mirrors.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from superharness.engine.state_errors import StateError


@dataclass(frozen=True)
class AgentRuntimeStatusRow:
    runtime: str
    schema_version: str
    liveness: str
    active_task: str | None
    next_wake_at: str | None
    budget: dict | None
    updated_at: str


def upsert(
    conn: sqlite3.Connection,
    *,
    runtime: str,
    schema_version: str = "1",
    liveness: str = "active",
    active_task: str | None = None,
    next_wake_at: str | None = None,
    budget: dict | None = None,
    updated_at: str,
) -> AgentRuntimeStatusRow:
    budget_json = json.dumps(budget) if budget is not None else None
    try:
        conn.execute(
            """
            INSERT INTO agent_runtime_status (
                runtime, schema_version, liveness, active_task,
                next_wake_at, budget_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(runtime) DO UPDATE SET
                schema_version=excluded.schema_version,
                liveness=excluded.liveness,
                active_task=excluded.active_task,
                next_wake_at=excluded.next_wake_at,
                budget_json=excluded.budget_json,
                updated_at=excluded.updated_at
            """,
            (runtime, schema_version, liveness, active_task,
             next_wake_at, budget_json, updated_at),
        )
        row = conn.execute(
            "SELECT * FROM agent_runtime_status WHERE runtime = ?", (runtime,)
        ).fetchone()
        if not row:
            raise StateError("agent_runtime_status upsert returned no row")
        return _to_row(row)
    except sqlite3.Error as e:
        raise StateError(f"agent_runtime_status upsert failed: {e}") from e


def get(conn: sqlite3.Connection, runtime: str) -> AgentRuntimeStatusRow | None:
    try:
        row = conn.execute(
            "SELECT * FROM agent_runtime_status WHERE runtime = ?", (runtime,)
        ).fetchone()
        return _to_row(row) if row else None
    except sqlite3.Error as e:
        raise StateError(f"agent_runtime_status get failed: {e}") from e


def get_all(conn: sqlite3.Connection) -> list[AgentRuntimeStatusRow]:
    try:
        rows = conn.execute(
            "SELECT * FROM agent_runtime_status ORDER BY updated_at DESC"
        ).fetchall()
        return [_to_row(r) for r in rows]
    except sqlite3.Error as e:
        raise StateError(f"agent_runtime_status get_all failed: {e}") from e


def _to_row(row: sqlite3.Row) -> AgentRuntimeStatusRow:
    raw_budget = row["budget_json"]
    budget: dict | None = None
    if raw_budget:
        try:
            parsed = json.loads(raw_budget)
            if isinstance(parsed, dict):
                budget = parsed
        except (ValueError, TypeError):
            budget = None
    return AgentRuntimeStatusRow(
        runtime=row["runtime"],
        schema_version=row["schema_version"],
        liveness=row["liveness"],
        active_task=row["active_task"],
        next_wake_at=row["next_wake_at"],
        budget=budget,
        updated_at=row["updated_at"],
    )
