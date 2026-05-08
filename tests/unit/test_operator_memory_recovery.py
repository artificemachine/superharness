"""Unit tests for _learn_from_recovery and _prune_operator_memory hooks."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from superharness.engine.operator_memory import OperatorMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_with_failures_and_done_task(tmp_path):
    """Create a project where a task failed, was recorded in failures table, then recovered to done."""
    sh = tmp_path / ".superharness"
    sh.mkdir()

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import failures_dao
    from superharness.engine import tasks_dao
    from superharness.engine.contract_io import _task_row_from_dict

    conn = get_connection(str(tmp_path))
    init_db(conn)

    # Insert a done task
    task_dict = {
        "id": "task-abc", "title": "Test task", "owner": "claude-code",
        "status": "done", "project_path": str(tmp_path),
    }
    tasks_dao.upsert(conn, _task_row_from_dict(task_dict, str(tmp_path), "2026-01-01T00:00:00Z"))

    # Record a failure for this task
    failures_dao.record(conn, task_id="task-abc", agent="claude-code",
                        pattern="import_error", error_snippet="ModuleNotFoundError",
                        now="2026-01-01T00:01:00Z")

    conn.commit()
    conn.close()

    # Seed operator_memory with the pattern
    db_path = str(sh / "state.sqlite3")
    om = OperatorMemory(db_path)
    om.ensure_table()
    om.record_new("import_error", "pip install -e .")
    # Give it low confidence (simulate previous misses)
    om.record_match("import_error", success=False)

    return tmp_path


@pytest.fixture
def project_with_only_failed_tasks(tmp_path):
    """Tasks with failures but status != done — no hits should be recorded."""
    sh = tmp_path / ".superharness"
    sh.mkdir()

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import failures_dao
    from superharness.engine import tasks_dao
    from superharness.engine.contract_io import _task_row_from_dict

    conn = get_connection(str(tmp_path))
    init_db(conn)

    # Task still failed, not recovered
    task_dict = {
        "id": "task-xyz", "title": "Failed task", "owner": "claude-code",
        "status": "failed", "project_path": str(tmp_path),
    }
    tasks_dao.upsert(conn, _task_row_from_dict(task_dict, str(tmp_path), "2026-01-01T00:00:00Z"))

    failures_dao.record(conn, task_id="task-xyz", agent="claude-code",
                        pattern="import_error", error_snippet="ModuleNotFoundError",
                        now="2026-01-01T00:01:00Z")

    conn.commit()
    conn.close()

    db_path = str(sh / "state.sqlite3")
    om = OperatorMemory(db_path)
    om.ensure_table()
    om.record_new("import_error", "pip install -e .")
    om.record_match("import_error", success=False)

    return tmp_path


# ---------------------------------------------------------------------------
# _learn_from_recovery
# ---------------------------------------------------------------------------

def test_learn_from_recovery_records_hits(project_with_failures_and_done_task):
    """A task that was failed and is now done gets hit recorded for its patterns."""
    from superharness.commands.inbox_watch import _learn_from_recovery

    _learn_from_recovery(str(project_with_failures_and_done_task))

    db_path = str(project_with_failures_and_done_task / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)
    result = om.find_pattern("import_error")
    assert result is not None
    assert result["hit_count"] >= 1
    assert result["confidence"] > 0.0


def test_learn_from_recovery_skips_still_failed(project_with_only_failed_tasks):
    """Tasks still in failed status do NOT get hits."""
    from superharness.commands.inbox_watch import _learn_from_recovery

    _learn_from_recovery(str(project_with_only_failed_tasks))

    db_path = str(project_with_only_failed_tasks / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)
    result = om.find_pattern("import_error")
    assert result["hit_count"] == 0  # unchanged


def test_learn_from_recovery_no_db(tmp_path, capsys):
    """No state.sqlite3 — returns without error."""
    from superharness.commands.inbox_watch import _learn_from_recovery

    _learn_from_recovery(str(tmp_path))
    # No crash = pass


# ---------------------------------------------------------------------------
# _prune_operator_memory
# ---------------------------------------------------------------------------

def test_prune_removes_low_confidence(tmp_path):
    """Low-confidence patterns get pruned."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    db_path = str(sh / "state.sqlite3")

    om = OperatorMemory(db_path)
    om.ensure_table()
    om.record_new("bad_pattern", "some fix")
    om.record_match("bad_pattern", success=False)
    om.record_match("bad_pattern", success=False)
    om.record_match("bad_pattern", success=False)
    # hit=0, miss=3 → confidence 0.0

    om.record_new("good_pattern", "working fix")
    om.record_match("good_pattern", success=True)
    # hit=1, miss=0 → confidence 1.0

    from superharness.commands.inbox_watch import _prune_operator_memory
    _prune_operator_memory(str(tmp_path))

    remaining = om.list_all()
    sigs = {r["pattern_signature"] for r in remaining}
    assert "bad_pattern" not in sigs
    assert "good_pattern" in sigs


def test_prune_no_db_graceful(tmp_path):
    """No state.sqlite3 — returns without error."""
    from superharness.commands.inbox_watch import _prune_operator_memory
    _prune_operator_memory(str(tmp_path))
    # No crash = pass
