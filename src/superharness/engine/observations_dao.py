"""DAO for task_observations.

Stores per-task observation snapshots written at lifecycle transitions
(today: only when an external caller writes one; later: auto-emitted at
report_ready by a summarizer). The DAO is storage-only. No LLM call,
no transition hook, no policy here.

Pattern: mirrors the operator_memory DAO style.

Privacy: insert() strips <private>...</private> spans before write.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from superharness.engine.db import now_iso
from superharness.utils.privacy import strip_private_tags


def insert(
    conn: sqlite3.Connection,
    task_id: str,
    phase: str,
    summary: str,
) -> int:
    """Insert an observation. Returns the new row id.

    Raises ValueError if task_id or summary is empty after privacy strip.
    """
    if not task_id:
        raise ValueError("task_id is required")
    cleaned = strip_private_tags(summary)
    if not cleaned:
        raise ValueError("summary is required (empty after privacy strip)")

    cur = conn.execute(
        """
        INSERT INTO task_observations (task_id, phase, summary, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (task_id, phase, cleaned, now_iso()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_by_id(conn: sqlite3.Connection, obs_id: int) -> dict[str, Any] | None:
    """Return the observation row as a dict, or None if not found."""
    row = conn.execute(
        "SELECT id, task_id, phase, summary, created_at FROM task_observations WHERE id = ?",
        (obs_id,),
    ).fetchone()
    if row is None:
        return None
    return dict(row)


def list_for_task(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    """Return all observations for a task, oldest first."""
    rows = conn.execute(
        """
        SELECT id, task_id, phase, summary, created_at
        FROM task_observations
        WHERE task_id = ?
        ORDER BY id ASC
        """,
        (task_id,),
    ).fetchall()
    return [dict(r) for r in rows]
