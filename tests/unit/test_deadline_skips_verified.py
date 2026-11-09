"""Regression: _check_deadlines must not force-fail a task whose report was verified.

Bug (2026-10-31, daryl t-84226c): a report_ready task was verified PASS
(verified=1, verified_at 23:42:29Z) and waited for the PM to close it. Ten
minutes later the legacy deadline sweep failed it with "deadline exceeded
(17m elapsed >= 10m limit) — task was in status 'report_ready'". shux then
refused to close a failed task, so a verified PASS could no longer be recorded.
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


def _insert(conn, task_id, status, verified):
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at, "
        "in_progress_at, deadline_minutes, verified, verified_at, verified_by, "
        "acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            task_id,
            f"Task {task_id}",
            "pi",
            status,
            _iso(-20),
            _iso(-20),
            _iso(-17),  # started 17 min ago
            10,  # 10-min budget, exceeded
            1 if verified else 0,
            _iso(-10) if verified else None,
            "codex-cli" if verified else None,
            "[]",
            "[]",
            "[]",
            "[]",
        ),
    )
    conn.commit()


@pytest.mark.regression
def test_verified_report_ready_task_survives_deadline(tmp_path):
    project, conn = _setup(tmp_path)
    _insert(conn, "verified-awaiting-close", "report_ready", verified=True)
    from superharness.engine.lifecycle_rules import _check_deadlines

    failed = _check_deadlines(str(project), {})

    row = conn.execute(
        "SELECT status, failed_reason FROM tasks WHERE id='verified-awaiting-close'"
    ).fetchone()
    assert failed == 0, "a verified task must not be deadline-failed"
    assert row[0] == "report_ready", f"expected report_ready, got {row[0]} ({row[1]})"


def test_unverified_report_ready_task_still_fails_deadline(tmp_path):
    project, conn = _setup(tmp_path)
    _insert(conn, "unverified-overran", "report_ready", verified=False)
    from superharness.engine.lifecycle_rules import _check_deadlines

    failed = _check_deadlines(str(project), {})

    row = conn.execute("SELECT status FROM tasks WHERE id='unverified-overran'").fetchone()
    assert failed == 1
    assert row[0] == "failed"
