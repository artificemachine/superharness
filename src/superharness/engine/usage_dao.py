from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import cast

from superharness.engine.db import now_iso
from superharness.engine.state_errors import StateError

@dataclass(frozen=True)
class UsageRow:
    id: int
    task_id: str
    agent: str
    source: str
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    recorded_at: str

def record(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    agent: str,
    source: str = "manual",
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    cost_usd: float | None = None,
    now: str | None = None,
) -> int:
    """Append a task_usage row. Append-only: never updates or deletes."""
    recorded_at = now or now_iso()
    try:
        cursor = conn.execute(
            """
            INSERT INTO task_usage (
                task_id, agent, source, model, input_tokens, output_tokens, cost_usd, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, agent, source, model, input_tokens, output_tokens, cost_usd, recorded_at),
        )
        conn.commit()
        return cast(int, cursor.lastrowid)
    except sqlite3.Error as e:
        raise StateError(f"Failed to record task_usage for task '{task_id}': {e}") from e

def list_for_task(conn: sqlite3.Connection, task_id: str) -> list[UsageRow]:
    """Return all usage rows for a task, ordered by recorded_at ASC."""
    cursor = conn.execute(
        "SELECT * FROM task_usage WHERE task_id = ? ORDER BY recorded_at ASC, id ASC",
        (task_id,),
    )
    return [_row_to_usage(row) for row in cursor.fetchall()]

def totals_by_agent(conn: sqlite3.Connection) -> dict[str, dict[str, float | int]]:
    """Aggregate input_tokens, output_tokens, cost_usd, and distinct task_count per agent.

    cost_usd is summed with NULLs excluded; input/output tokens likewise.
    """
    cursor = conn.execute(
        """
        SELECT
            agent,
            COALESCE(SUM(input_tokens), 0)  AS input_tokens,
            COALESCE(SUM(output_tokens), 0) AS output_tokens,
            COALESCE(SUM(cost_usd), 0.0)    AS cost_usd,
            COUNT(DISTINCT task_id)         AS task_count
        FROM task_usage
        GROUP BY agent
        """
    )
    totals: dict[str, dict[str, float | int]] = {}
    for row in cursor.fetchall():
        totals[row["agent"]] = {
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "cost_usd": row["cost_usd"],
            "task_count": row["task_count"],
        }
    return totals

def _row_to_usage(row: sqlite3.Row) -> UsageRow:
    return UsageRow(
        id=row["id"],
        task_id=row["task_id"],
        agent=row["agent"],
        source=row["source"],
        model=row["model"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cost_usd=row["cost_usd"],
        recorded_at=row["recorded_at"],
    )
