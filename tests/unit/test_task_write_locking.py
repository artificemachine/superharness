"""Iteration 7 — route task-status writes through the version-checked DAO.

Before this fix, 17 of 18 task writers in the codebase bypassed
`tasks_dao.update`'s optimistic-locking `WHERE id=? AND version=?` clause —
the watcher's auto-recovery/reconciliation paths wrote `status` (and other
columns) via seven raw `UPDATE tasks ...` statements with no version check
at all, and `ConcurrencyError` (defined in engine/state_errors.py) was
caught nowhere in the codebase. A concurrent writer could silently clobber
another agent's change.
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

import pytest

from superharness.engine import tasks_dao
from superharness.engine.state_errors import ConcurrencyError
from superharness.commands import inbox_watch


_INBOX_WATCH_SRC = (
    Path(__file__).resolve().parents[2]
    / "src" / "superharness" / "commands" / "inbox_watch.py"
)


@pytest.fixture
def db_conn(tmp_path: Path):
    """Same shape as tests/unit/db/conftest.py's db_conn — that fixture is
    scoped to tests/unit/db/ only, and this file lives one level up."""
    from superharness.engine.db import get_connection, init_db
    from superharness.utils.paths import resolve_xdg_state_db_path
    project = tmp_path
    (project / ".superharness").mkdir()
    conn = get_connection(str(project))
    init_db(conn)
    yield conn
    conn.close()
    xdg_db = resolve_xdg_state_db_path(str(project))
    if os.path.isfile(xdg_db):
        try:
            os.remove(xdg_db)
        except OSError:
            pass


def _seed_task(conn, task_id="t-lock", status="todo"):
    conn.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) "
        "VALUES (?, ?, ?, 1, '2026-01-01T00:00:00Z')",
        (task_id, task_id, status),
    )
    conn.commit()


class TestSetStatus:
    def test_set_status_bumps_version(self, db_conn):
        _seed_task(db_conn, "t-1", "todo")
        tasks_dao.set_status(db_conn, "t-1", "plan_proposed", expected_version=1)
        row = tasks_dao.get(db_conn, "t-1")
        assert row.status == "plan_proposed"
        assert row.version == 2

    def test_set_status_raises_on_stale_version(self, db_conn):
        _seed_task(db_conn, "t-2", "todo")
        tasks_dao.set_status(db_conn, "t-2", "plan_proposed", expected_version=1)
        # version is now 2 — retrying with the stale expected_version=1 must fail
        with pytest.raises(ConcurrencyError):
            tasks_dao.set_status(db_conn, "t-2", "in_progress", expected_version=1)


class TestWatcherTaskLockRetry:
    def test_watcher_retries_once_on_conflict(self, db_conn):
        _seed_task(db_conn, "t-3", "todo")

        calls = {"n": 0}
        real_set_status = tasks_dao.set_status

        def flaky_set_status(conn, task_id, new_status, expected_version, **fields):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConcurrencyError("simulated conflict on first attempt")
            return real_set_status(conn, task_id, new_status, expected_version, **fields)

        with patch.object(tasks_dao, "set_status", side_effect=flaky_set_status):
            result = inbox_watch._with_task_lock(
                db_conn, "t-3", {"status": "plan_proposed"}, context="test",
            )

        assert calls["n"] == 2, "must retry exactly once after a single conflict"
        assert result is not None
        row = tasks_dao.get(db_conn, "t-3")
        assert row.status == "plan_proposed"

    def test_watcher_logs_and_skips_after_repeated_conflict(self, db_conn, caplog):
        _seed_task(db_conn, "t-4", "todo")

        def always_conflict(conn, task_id, new_status, expected_version, **fields):
            raise ConcurrencyError("simulated persistent conflict")

        with patch.object(tasks_dao, "set_status", side_effect=always_conflict):
            with caplog.at_level(logging.WARNING, logger="superharness.commands.inbox_watch"):
                result = inbox_watch._with_task_lock(
                    db_conn, "t-4", {"status": "plan_proposed"}, context="test",
                )

        assert result is None, "a repeated conflict must be skipped, not raised"
        row = tasks_dao.get(db_conn, "t-4")
        assert row.status == "todo", "the task must be left untouched, not silently overwritten"
        assert any("conflict" in r.message.lower() for r in caplog.records), (
            "a repeated conflict must be logged"
        )


def test_no_raw_update_tasks_remains_in_watcher():
    src = _INBOX_WATCH_SRC.read_text()
    assert "UPDATE tasks" not in src, (
        "a raw UPDATE tasks statement reappeared in inbox_watch.py — task "
        "writes must go through tasks_dao.set_status/update"
    )


def test_telegram_reset_targets_todo_not_pending():
    """`/reset` must return a task to the start of the *task* lifecycle.

    It previously mapped to "pending", which is the initial status of a
    decomposed *subtask* (commands/delegate.py:320,354) — not a status any
    top-level task lifecycle rule matches. v1.80.2 made that write fail loudly
    via tasks_dao.VALID_STATUSES rather than silently corrupt tasks.status, and
    left the semantics as an open decision.

    Migration v35 adds "pending" to the vocabulary so subtask rows satisfy the
    new CHECK constraint. That legitimises the value for subtasks — and would
    have silently re-legitimised this bug with it, letting /reset write a
    status no lifecycle rule advances, which is exactly the invisible-stuck
    task the constraint exists to prevent. "todo" is the correct target.
    """
    import re
    from pathlib import Path

    # Anchor to repo root, not CWD: an earlier test that chdir's into a tmp
    # dir without restoring would otherwise make this relative read raise
    # FileNotFoundError depending on test ordering.
    _repo_root = Path(__file__).resolve().parents[2]
    src = (_repo_root / "src/superharness/modules/gateway/telegram_gateway.py").read_text()
    mapping = re.search(r'"reset":\s*\(\s*"([a-z_]+)"', src)
    assert mapping is not None, "could not find the /reset status mapping"
    assert mapping.group(1) == "todo", (
        f'/reset maps to {mapping.group(1)!r}; it must map to "todo" — '
        '"pending" is the subtask initial status, not a task lifecycle entry point'
    )
