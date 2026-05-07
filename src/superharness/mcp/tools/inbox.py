"""MCP inbox tools — Iteration 6."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_inbox(
    conn: sqlite3.Connection,
    status_filter: Optional[list[str]] = None,
) -> list[dict]:
    """Return inbox items, optionally filtered by status."""
    try:
        if status_filter:
            placeholders = ",".join(["?" for _ in status_filter])
            cursor = conn.execute(
                f"SELECT * FROM inbox WHERE status IN ({placeholders}) ORDER BY created_at ASC",
                status_filter,
            )
        else:
            cursor = conn.execute("SELECT * FROM inbox ORDER BY created_at ASC")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            if hasattr(row, "keys"):
                d = dict(zip(row.keys(), tuple(row)))
            else:
                d = dict(row)
            # normalize to consistent field names for tool consumers
            d.setdefault("task", d.get("task_id", ""))
            d.setdefault("to", d.get("target_agent", ""))
            result.append(d)
        return result
    except Exception:
        return []


def enqueue_task(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    target: str,
    project_path: str,
    gate=None,
    conn_id: str = "anon",
    hook_registry=None,
) -> dict:
    """Enqueue a task for dispatch.

    If *gate* is provided, calls gate.check("enqueue", conn_id, project_path)
    which may raise ApprovalPending.
    """
    if gate is not None:
        gate.check("enqueue", conn_id=conn_id, project_path=project_path)

    item_id = str(uuid.uuid4())
    now = _now()
    conn.execute("""
        INSERT OR IGNORE INTO inbox
        (id, task_id, target_agent, status, created_at, retry_count, max_retries, project_path)
        VALUES (?, ?, ?, 'pending', ?, 0, 3, ?)
    """, (item_id, task_id, target, now, project_path))
    conn.commit()

    if hook_registry:
        hook_registry.fire("task:delegated", {"task_id": task_id, "target": target},
                           project_path=project_path)

    return {"id": item_id, "task": task_id, "to": target, "status": "pending"}
