"""Insights engine — task/dispatch/agent breakdowns from SQLite."""
from __future__ import annotations

import os
import sqlite3


def get_insights(project_dir: str) -> dict:
    """Return aggregated insights from the SQLite state DB.

    Returns:
        dict with keys: tasks, agents, dispatch, failures
    """
    db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
    if not os.path.isfile(db_path):
        return {"tasks": {}, "agents": {}, "dispatch": {}, "failures": []}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return {
            "tasks": _task_counts(conn),
            "agents": _agent_breakdown(conn),
            "dispatch": _dispatch_counts(conn),
            "failures": _top_failures(conn),
        }
    finally:
        conn.close()


def _task_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) as n FROM tasks GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def _agent_breakdown(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT owner, status, COUNT(*) as n FROM tasks WHERE owner IS NOT NULL GROUP BY owner, status"
    ).fetchall()
    result: dict[str, dict[str, int]] = {}
    for r in rows:
        agent = r["owner"]
        if agent not in result:
            result[agent] = {}
        result[agent][r["status"]] = r["n"]
    return result


def _dispatch_counts(conn: sqlite3.Connection) -> dict:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    launched = 0
    failed = 0
    if "ledger" in tables:
        row = conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE action='dispatch_launched'"
        ).fetchone()
        launched = row[0] if row else 0
        row = conn.execute(
            "SELECT COUNT(*) FROM ledger WHERE action='dispatch_failed'"
        ).fetchone()
        failed = row[0] if row else 0
    return {"launched": launched, "failed": failed}


def _top_failures(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "inbox" not in tables:
        return []
    rows = conn.execute(
        """SELECT task_id, target_agent, MAX(retry_count) as retry_count, failed_reason
           FROM inbox WHERE status='failed'
           GROUP BY task_id, target_agent
           ORDER BY retry_count DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
