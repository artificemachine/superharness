"""Auto-capture an observation snapshot at a lifecycle transition.

The capture is wholly defensive: any internal exception is swallowed and
the function returns None. Callers (today: the state_writer's
set_task_status path) must never have a status transition fail because
the summarizer is misconfigured or the DAO write hit a constraint.

Borrowed from claude-mem in spirit: capture happens at a lifecycle
boundary, the summary is computed by a pluggable provider, and the
result is stored for later retrieval. Differs from claude-mem in two
important ways: the snapshot is never auto-injected into a future
prompt, and the capture cadence is lifecycle transitions only (not
every tool call).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from superharness.engine import handoffs_dao, observations_dao, tasks_dao
from superharness.engine.summarizer import Summarizer, get_summarizer


def _build_context(conn: sqlite3.Connection, task_id: str, phase: str) -> dict[str, Any] | None:
    task = tasks_dao.get(conn, task_id)
    if task is None:
        return None

    ctx: dict[str, Any] = {
        "task_id": task.id,
        "phase": phase,
        "title": task.title,
        "owner": task.owner,
    }

    latest_report = handoffs_dao.get_latest(conn, task_id, "report")
    if latest_report is not None:
        ctx["outcome"] = latest_report.content or ""
        ctx["from_agent"] = latest_report.from_agent or ""
        ctx["to_agent"] = latest_report.to_agent or ""
        ctx["created_at"] = latest_report.created_at
    return ctx


def capture_observation(
    conn: sqlite3.Connection,
    task_id: str,
    phase: str,
    summarizer: Summarizer | None = None,
    *,
    project_dir: str | None = None,
) -> int | None:
    """Build context, summarize, insert. Returns observation id or None.

    Never raises. Any exception is caught and surfaced as None, so a
    failing summarizer or DAO write cannot break a status transition.

    `project_dir`, when set, enables cross-process rate limiting and
    call logging via the summarizer_calls table.
    """
    try:
        ctx = _build_context(conn, task_id, phase)
        if ctx is None:
            return None

        s = summarizer if summarizer is not None else get_summarizer(project_dir=project_dir)
        summary = s.summarize(ctx)
        if not summary:
            return None

        return observations_dao.insert(conn, task_id, phase, summary)
    except Exception:
        return None
