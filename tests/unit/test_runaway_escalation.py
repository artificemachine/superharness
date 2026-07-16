"""Fix B — auto-recover escalates runaway loops to waiting_input.

Two escalation triggers:
1. inbox.max_retries reaches the absolute ceiling (no more bumps).
2. The same error_snippet has been recorded N times in a row for this
   task — indicates an environmental fault that no agent reroute will fix.
"""
from __future__ import annotations

import os
from unittest.mock import patch

from superharness.engine.db import get_connection, init_db
from superharness.commands.inbox_watch import (
    _ABSOLUTE_MAX_RETRIES,
    _IDENTICAL_FAILURE_THRESHOLD,
    _auto_recover_exhausted_failures_sqlite,
    _has_identical_failure_loop,
)


NOW = "2026-05-08T00:00:00Z"


def _setup(tmp_path):
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn, str(project))
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, updated_at) "
        "VALUES ('t1', 't', 'claude-code', 'in_progress', ?, ?)",
        (NOW, NOW),
    )
    conn.commit()
    return str(project), conn


def _seed_inbox(conn, *, recovery_count, max_retries, retry_count, status="failed"):
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, retry_count, "
        "max_retries, recovery_count, failed_reason, created_at) "
        "VALUES ('i1', 't1', 'claude-code', ?, ?, ?, ?, "
        "'unknown: unclassified failure (exit code 1)', ?)",
        (status, retry_count, max_retries, recovery_count, NOW),
    )
    conn.commit()


def _seed_failures(conn, *, snippets):
    """Seed N rows in the failures table. Pass a list of snippets in
    chronological order — order matters for the 'last N' check."""
    for i, snip in enumerate(snippets):
        conn.execute(
            "INSERT INTO failures (task_id, agent, pattern, error_snippet, created_at) "
            "VALUES ('t1', 'claude-code', 'unknown', ?, ?)",
            (snip, f"2026-05-08T00:00:{i:02d}Z"),
        )
    conn.commit()


def test_identical_failure_loop_detector_returns_true_when_all_match(tmp_path):
    project, conn = _setup(tmp_path)
    try:
        _seed_failures(
            conn,
            snippets=["Discussion directory not found"] * _IDENTICAL_FAILURE_THRESHOLD,
        )
        assert _has_identical_failure_loop(conn, "t1") is True
    finally:
        conn.close()


def test_identical_failure_loop_detector_false_when_mixed(tmp_path):
    project, conn = _setup(tmp_path)
    try:
        _seed_failures(
            conn,
            snippets=["err A", "err A", "err B", "err A"],
        )
        assert _has_identical_failure_loop(conn, "t1") is False
    finally:
        conn.close()


def test_identical_failure_loop_detector_false_below_threshold(tmp_path):
    project, conn = _setup(tmp_path)
    try:
        _seed_failures(conn, snippets=["err"] * (_IDENTICAL_FAILURE_THRESHOLD - 1))
        assert _has_identical_failure_loop(conn, "t1") is False
    finally:
        conn.close()


def test_auto_recover_escalates_when_max_retries_hits_ceiling(tmp_path):
    """Once max_retries >= _ABSOLUTE_MAX_RETRIES, no more bumps —
    escalate the task to waiting_input and close the inbox row."""
    project, conn = _setup(tmp_path)
    _seed_inbox(
        conn,
        recovery_count=10,
        max_retries=_ABSOLUTE_MAX_RETRIES,
        retry_count=_ABSOLUTE_MAX_RETRIES,
    )
    conn.close()

    _auto_recover_exhausted_failures_sqlite(project)

    conn = get_connection(project)
    try:
        task_status = conn.execute(
            "SELECT status FROM tasks WHERE id='t1'"
        ).fetchone()["status"]
        inbox_status = conn.execute(
            "SELECT status FROM inbox WHERE id='i1'"
        ).fetchone()["status"]
        assert task_status == "waiting_input"
        # The escalation closes the inbox row (failed status with escalated reason).
        assert inbox_status == "failed"
    finally:
        conn.close()


def test_auto_recover_escalates_on_identical_error_loop(tmp_path):
    """Even with retries remaining, if the same error_snippet has
    repeated >= threshold times the task escalates."""
    project, conn = _setup(tmp_path)
    _seed_inbox(
        conn,
        recovery_count=0,
        max_retries=3,  # well below ceiling
        retry_count=3,  # exhausted retries → enters auto_recover
    )
    _seed_failures(
        conn,
        snippets=["Discussion directory not found"] * _IDENTICAL_FAILURE_THRESHOLD,
    )
    conn.close()

    _auto_recover_exhausted_failures_sqlite(project)

    conn = get_connection(project)
    try:
        task_status = conn.execute(
            "SELECT status FROM tasks WHERE id='t1'"
        ).fetchone()["status"]
        assert task_status == "waiting_input"
    finally:
        conn.close()


def test_auto_recover_writes_recovery_count_to_column_not_failed_reason(tmp_path):
    """Regression for Fix A: the recovery counter must be persisted in
    its own column so subsequent failures cannot wipe it.

    Mocks CLI reachability rather than relying on the test machine having
    the fallback agents' binaries on PATH (not true on CI runners) — this
    test is about recovery_count persistence, not real CLI availability.
    """
    project, conn = _setup(tmp_path)
    _seed_inbox(
        conn,
        recovery_count=0,
        max_retries=3,
        retry_count=3,
    )
    # No identical-error loop seeded → should re-route normally.
    conn.close()

    with patch("superharness.commands.inbox_watch._agent_cli_reachable", return_value=True):
        _auto_recover_exhausted_failures_sqlite(project)

    conn = get_connection(project)
    try:
        row = conn.execute(
            "SELECT recovery_count, max_retries, status, failed_reason "
            "FROM inbox WHERE id='i1'"
        ).fetchone()
        assert row["recovery_count"] == 1, "counter must be in column"
        assert row["status"] == "pending"
        assert row["max_retries"] == 4  # bumped by 1
    finally:
        conn.close()
