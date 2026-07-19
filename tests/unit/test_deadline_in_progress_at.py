"""Regression: _check_deadlines must measure a running task's deadline from
when work started (in_progress_at), not from task creation (created_at).

Bug (2026-07-19 job-ready audit, lifecycle_rules.py): a task that sat in the
backlog for a long time, then got approved and dispatched, was force-failed on
the first deadline sweep because age was measured from created_at — its whole
queue time counted against a deadline meant to budget actual work.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _iso(offset_minutes: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    (tmp_path / ".superharness").mkdir()
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return tmp_path, conn


def _insert(conn, task_id, status, created_at, in_progress_at, deadline_minutes):
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at, "
        "in_progress_at, deadline_minutes, acceptance_criteria, test_types, "
        "out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (task_id, f"Task {task_id}", "claude-code", status,
         created_at, created_at, in_progress_at, deadline_minutes,
         "[]", "[]", "[]", "[]"),
    )
    conn.commit()


def test_running_task_not_failed_when_recently_started(tmp_path):
    """Old created_at + recent in_progress_at + short deadline → must survive."""
    project, conn = _setup(tmp_path)
    _insert(
        conn, "queued-then-run", "in_progress",
        created_at=_iso(-600),        # created 10h ago (sat in backlog)
        in_progress_at=_iso(-2),      # work started 2 min ago
        deadline_minutes=30,          # 30-min work budget, not yet exceeded
    )
    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {})

    row = conn.execute(
        "SELECT status FROM tasks WHERE id='queued-then-run'"
    ).fetchone()
    assert failed == 0, "recently-started task must not be deadline-failed"
    assert row[0] == "in_progress", f"expected in_progress, got {row[0]}"


def test_running_task_failed_when_work_actually_overran(tmp_path):
    """in_progress_at older than deadline → still fails (deadline stays enforced)."""
    project, conn = _setup(tmp_path)
    _insert(
        conn, "genuinely-overran", "in_progress",
        created_at=_iso(-600),
        in_progress_at=_iso(-90),     # started 90 min ago
        deadline_minutes=30,          # 30-min budget blown
    )
    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {})

    row = conn.execute(
        "SELECT status FROM tasks WHERE id='genuinely-overran'"
    ).fetchone()
    assert failed == 1
    assert row[0] == "failed"


def test_pre_work_task_still_uses_created_at(tmp_path):
    """A task never started (no in_progress_at) falls back to created_at so
    backlog staleness is still caught."""
    project, conn = _setup(tmp_path)
    _insert(
        conn, "stale-backlog", "todo",
        created_at=_iso(-600),
        in_progress_at=None,
        deadline_minutes=30,
    )
    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {})

    row = conn.execute(
        "SELECT status FROM tasks WHERE id='stale-backlog'"
    ).fetchone()
    assert failed == 1
    assert row[0] == "failed"
