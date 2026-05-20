"""Tests for worktree surface in shux status and dashboard snapshot."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from superharness.engine import tasks_dao
from superharness.engine.contract_io import _task_row_from_dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "profile.yaml").write_text(
        "auto_dispatch: false\nauto_close: false\nauto_approve_plans: false\n"
    )
    return project


def _local_conn(project: Path) -> sqlite3.Connection:
    """Direct connection to the local legacy db (bypasses SUPERHARNESS_STATE_PROJECT)."""
    legacy_db = project / ".superharness" / "state.sqlite3"
    conn = sqlite3.connect(str(legacy_db))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    return conn


def _seed_task(conn: sqlite3.Connection, project: Path, task_id: str, worktree_path: str | None) -> None:
    row = _task_row_from_dict(
        {
            "id": task_id,
            "title": f"Task {task_id}",
            "status": "in_progress",
            "owner": "claude-code",
            "acceptance_criteria": [],
            "worktree_path": worktree_path,
        },
        str(project),
        "2026-05-20T10:00:00Z",
    )
    tasks_dao.upsert(conn, row)
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolate_state_project(monkeypatch):
    """Prevent SUPERHARNESS_STATE_PROJECT from redirecting DB reads to the real project."""
    monkeypatch.delenv("SUPERHARNESS_STATE_PROJECT", raising=False)


# ---------------------------------------------------------------------------
# _active_worktrees
# ---------------------------------------------------------------------------

class TestActiveWorktrees:
    def test_empty_when_no_tasks(self, tmp_path):
        project = _make_project(tmp_path)
        _local_conn(project).close()

        from superharness.commands.status import _active_worktrees
        assert _active_worktrees(str(project)) == []

    def test_empty_when_no_worktree_path(self, tmp_path):
        project = _make_project(tmp_path)
        conn = _local_conn(project)
        _seed_task(conn, project, "task-a", None)
        conn.close()

        from superharness.commands.status import _active_worktrees
        assert _active_worktrees(str(project)) == []

    def test_empty_when_dir_missing(self, tmp_path):
        project = _make_project(tmp_path)
        conn = _local_conn(project)
        _seed_task(conn, project, "task-b", "/nonexistent/path/task-b")
        conn.close()

        from superharness.commands.status import _active_worktrees
        assert _active_worktrees(str(project)) == []

    def test_returns_entry_when_dir_exists(self, tmp_path):
        project = _make_project(tmp_path)
        wt_dir = tmp_path / "worktrees" / "task-c"
        wt_dir.mkdir(parents=True)

        conn = _local_conn(project)
        _seed_task(conn, project, "task-c", str(wt_dir))
        conn.close()

        from superharness.commands.status import _active_worktrees
        result = _active_worktrees(str(project))
        assert len(result) == 1
        assert result[0]["task_id"] == "task-c"
        assert result[0]["path"] == str(wt_dir)
        assert "age_min" in result[0]

    def test_filters_missing_from_existing(self, tmp_path):
        project = _make_project(tmp_path)
        wt_dir = tmp_path / "worktrees" / "task-alive"
        wt_dir.mkdir(parents=True)

        conn = _local_conn(project)
        _seed_task(conn, project, "task-alive", str(wt_dir))
        _seed_task(conn, project, "task-dead", "/nonexistent/task-dead")
        conn.close()

        from superharness.commands.status import _active_worktrees
        result = _active_worktrees(str(project))
        assert len(result) == 1
        assert result[0]["task_id"] == "task-alive"


# ---------------------------------------------------------------------------
# dashboard_presenter worktrees field
# ---------------------------------------------------------------------------

class TestDashboardWorktrees:
    def test_worktrees_key_present_when_empty(self, tmp_path):
        project = _make_project(tmp_path)
        conn = _local_conn(project)

        from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
        snapshot = get_dashboard_status_snapshot(conn, str(project))
        conn.close()

        assert "worktrees" in snapshot
        assert snapshot["worktrees"] == []

    def test_worktrees_included_when_dir_exists(self, tmp_path):
        project = _make_project(tmp_path)
        wt_dir = tmp_path / "worktrees" / "feat-x"
        wt_dir.mkdir(parents=True)

        conn = _local_conn(project)
        _seed_task(conn, project, "feat-x", str(wt_dir))

        from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
        snapshot = get_dashboard_status_snapshot(conn, str(project))
        conn.close()

        assert len(snapshot["worktrees"]) == 1
        wt = snapshot["worktrees"][0]
        assert wt["task_id"] == "feat-x"
        assert wt["path"] == str(wt_dir)
        assert "created_at" in wt

    def test_worktrees_omit_missing_dir(self, tmp_path):
        project = _make_project(tmp_path)
        conn = _local_conn(project)
        _seed_task(conn, project, "feat-gone", "/nonexistent/feat-gone")

        from superharness.engine.dashboard_presenter import get_dashboard_status_snapshot
        snapshot = get_dashboard_status_snapshot(conn, str(project))
        conn.close()

        assert snapshot["worktrees"] == []
