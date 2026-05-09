"""Per-task burst detection for auto-flow dispatch.

Any auto-flow that enqueues an inbox row for a task should call
task_burst_suppressed() first. If a task generates BURST_THRESHOLD or
more failed inbox rows within BURST_WINDOW_MINUTES, further dispatch for
that task is suppressed until the window clears naturally.

This is a broader safety net than the peer-review-specific cooldown in
inbox_watch — it catches any fast-failing loop regardless of which
auto-flow triggered it.
"""
from __future__ import annotations

import sqlite3

BURST_THRESHOLD = 5       # failed rows in the window before suppression
BURST_WINDOW_MINUTES = 10


def task_burst_suppressed(
    conn: sqlite3.Connection,
    task_id: str,
    *,
    threshold: int = BURST_THRESHOLD,
    window_minutes: int = BURST_WINDOW_MINUTES,
) -> bool:
    """Return True if task_id has generated too many failed inbox rows recently."""
    from datetime import datetime, timedelta, timezone
    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        row = conn.execute(
            "SELECT COUNT(*) FROM inbox "
            "WHERE task_id = ? AND status = 'failed' AND failed_at > ?",
            (task_id, cutoff),
        ).fetchone()
        count = row[0] if row else 0
        if count >= threshold:
            print(
                f"burst-guard: suppressing dispatch for '{task_id}' "
                f"({count} failed rows in {window_minutes}min)"
            )
            return True
        return False
    except Exception:
        return False
