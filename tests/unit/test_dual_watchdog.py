"""Dual watchdog: idle timeout + absolute ceiling, consuming iteration 7's
event stream. Extends lifecycle_rules._check_deadlines.

Regression hard gate: tests/unit/test_deadline_in_progress_at.py's 3 PR #43
tests must stay green UNMODIFIED (checked separately in this run, not
reproduced here).

See docs/PLAN-steal-omnigent.md iteration 8.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from superharness.engine.db import get_connection, init_db


def _iso(offset_minutes: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup(tmp_path: Path) -> tuple[Path, sqlite3.Connection]:
    (tmp_path / ".superharness").mkdir()
    conn = get_connection(str(tmp_path))
    init_db(conn)
    return tmp_path, conn


def _insert_task(conn, task_id, status, created_at, in_progress_at, deadline_minutes=None):
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


def _insert_event(conn, task_id, ts):
    conn.execute(
        "INSERT INTO events (ts, kind, task_id, payload_json) VALUES (?, 'transcript_progress', ?, '{}')",
        (ts, task_id),
    )
    conn.commit()


def test_active_task_survives_past_deadline_when_events_fresh(tmp_path):
    """in_progress 90m, deadline_minutes=30, but last event 1m ago and
    idle_timeout_minutes=10 -> NOT failed. Events prove liveness; only the
    absolute ceiling (unset here) can kill it."""
    project, conn = _setup(tmp_path)
    _insert_task(conn, "active", "in_progress",
                 created_at=_iso(-600), in_progress_at=_iso(-90), deadline_minutes=30)
    _insert_event(conn, "active", _iso(-1))

    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {"idle_timeout_minutes": 10})

    row = conn.execute("SELECT status FROM tasks WHERE id='active'").fetchone()
    assert failed == 0
    assert row[0] == "in_progress"


def test_idle_task_fails_at_idle_timeout(tmp_path):
    """in_progress 20m, last event 15m ago, idle_timeout 10 -> failed with
    reason containing 'idle'."""
    project, conn = _setup(tmp_path)
    _insert_task(conn, "idle-task", "in_progress",
                 created_at=_iso(-30), in_progress_at=_iso(-20))
    _insert_event(conn, "idle-task", _iso(-15))

    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {"idle_timeout_minutes": 10})

    row = conn.execute(
        "SELECT status, failed_reason FROM tasks WHERE id='idle-task'"
    ).fetchone()
    assert failed == 1
    assert row[0] == "failed"
    assert "idle" in row[1].lower()


def test_absolute_ceiling_kills_even_active(tmp_path):
    """in_progress beyond absolute_ceiling_minutes with fresh events ->
    failed with reason containing 'ceiling'."""
    project, conn = _setup(tmp_path)
    _insert_task(conn, "long-runner", "in_progress",
                 created_at=_iso(-600), in_progress_at=_iso(-120))
    _insert_event(conn, "long-runner", _iso(-1))

    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {
        "idle_timeout_minutes": 10,
        "absolute_ceiling_minutes": 60,
    })

    row = conn.execute(
        "SELECT status, failed_reason FROM tasks WHERE id='long-runner'"
    ).fetchone()
    assert failed == 1
    assert row[0] == "failed"
    assert "ceiling" in row[1].lower()


def test_no_events_falls_back_to_pr43_semantics(tmp_path):
    """No events rows for the task -> identical to PR #43 behavior
    (in_progress_at budget), even with idle_timeout_minutes enabled.
    Mirrors test_deadline_in_progress_at.py::
    test_running_task_failed_when_work_actually_overran."""
    project, conn = _setup(tmp_path)
    _insert_task(conn, "genuinely-overran", "in_progress",
                 created_at=_iso(-600), in_progress_at=_iso(-90), deadline_minutes=30)
    # No events rows inserted for this task at all.

    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {"idle_timeout_minutes": 10})

    row = conn.execute(
        "SELECT status, failed_reason FROM tasks WHERE id='genuinely-overran'"
    ).fetchone()
    assert failed == 1
    assert row[0] == "failed"
    assert "deadline exceeded" in row[1].lower()


def test_both_new_keys_unset_is_byte_identical_to_legacy(tmp_path):
    """With idle_timeout_minutes and absolute_ceiling_minutes both unset
    (0/absent), _check_deadlines output must be identical to pre-iteration
    behavior on the same fixture (PR #43's own recently-started-survives
    case)."""
    project, conn = _setup(tmp_path)
    _insert_task(conn, "queued-then-run", "in_progress",
                 created_at=_iso(-600), in_progress_at=_iso(-2), deadline_minutes=30)
    _insert_event(conn, "queued-then-run", _iso(-1))  # even with events present

    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {})  # no idle/ceiling keys at all

    row = conn.execute("SELECT status FROM tasks WHERE id='queued-then-run'").fetchone()
    assert failed == 0
    assert row[0] == "in_progress"


def test_full_loop_transcript_to_events_to_deadline_spares_active_task(tmp_path):
    """Integration crossing iterations 7 -> 8: fixture transcript ->
    tail_step -> events -> _check_deadlines spares the active task."""
    import json
    from superharness.engine import events as events_mod
    from superharness.engine.transcript_tail import tail_step

    project, conn = _setup(tmp_path)
    _insert_task(conn, "watched", "in_progress",
                 created_at=_iso(-600), in_progress_at=_iso(-90), deadline_minutes=30)
    conn.close()

    events_mod.configure(str(project))

    transcript = project / "session.jsonl"
    transcript.write_text(json.dumps({"type": "tool_use", "name": "Bash"}) + "\n")

    conn = get_connection(str(project))
    init_db(conn)
    emitted = tail_step(conn, "watched", transcript)
    conn.close()
    assert emitted == 1
    assert events_mod.flush(timeout=5) is True

    from superharness.engine.lifecycle_rules import _check_deadlines
    failed = _check_deadlines(str(project), {"idle_timeout_minutes": 10})

    conn = get_connection(str(project))
    row = conn.execute("SELECT status FROM tasks WHERE id='watched'").fetchone()
    conn.close()
    assert failed == 0
    assert row[0] == "in_progress"
