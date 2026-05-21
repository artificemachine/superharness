"""MCP contract tools — Iteration 5."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any, Optional

import logging
logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_dict(row) -> dict:
    if hasattr(row, "keys"):
        return dict(zip(row.keys(), tuple(row)))
    return dict(row)


def get_contract(conn: sqlite3.Connection) -> list[dict]:
    """Return all tasks as a list of dicts."""
    try:
        cursor = conn.execute("SELECT * FROM tasks ORDER BY created_at ASC")
        rows = cursor.fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("contract.py unexpected error: %s", e, exc_info=True)
        return []


def get_task(conn: sqlite3.Connection, task_id: str) -> Optional[dict]:
    """Return a single task by ID or None."""
    try:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("contract.py unexpected error: %s", e, exc_info=True)
        return None


def create_task(
    conn: sqlite3.Connection,
    *,
    id: str,
    title: str,
    owner: str,
    status: str = "todo",
) -> dict:
    """Create a new task. Returns the created task dict."""
    now = _now()
    conn.execute("""
        INSERT OR IGNORE INTO tasks (
            id, title, owner, status, created_at, updated_at, version,
            acceptance_criteria, test_types, out_of_scope, definition_of_done
        ) VALUES (?, ?, ?, ?, ?, ?, 1, '[]', '[]', '[]', '[]')
    """, (id, title, owner, status, now, now))
    conn.commit()
    return get_task(conn, id) or {}


def update_status(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    status: str,
    actor: str,
    summary: str = "",
    hook_registry=None,
    project_path: str = "",
) -> dict:
    """Update task status and optionally fire lifecycle hooks."""
    now = _now()
    status_col = f"{status}_at"
    # Map well-known statuses to their timestamp columns
    ts_cols = {
        "plan_proposed": "plan_proposed_at",
        "plan_approved": "plan_approved_at",
        "in_progress": "in_progress_at",
        "report_ready": "report_ready_at",
        "done": "done_at",
        "cancelled": "cancelled_at",
    }
    extra_col = ts_cols.get(status)
    if extra_col:
        conn.execute(f"""
            UPDATE tasks SET status=?, updated_at=?, version=version+1, {extra_col}=?
            WHERE id=?
        """, (status, now, now, task_id))
    else:
        conn.execute("""
            UPDATE tasks SET status=?, updated_at=?, version=version+1 WHERE id=?
        """, (status, now, task_id))
    conn.commit()

    if hook_registry and project_path:
        event = "task:completed" if status == "done" else f"task:{status}"
        hook_registry.fire(event, {"task_id": task_id, "status": status, "actor": actor},
                           project_path=project_path)

    return get_task(conn, task_id) or {}
