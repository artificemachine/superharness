"""Tests for `shux continue` — read-only active-contract resume helper.

continue resolves the most in-flight resumable task, prints its recommended
next action, and fires on_continue lifecycle hooks (the remember module's
refresh_context). It performs no status writes and no dispatch.
"""
from __future__ import annotations

from pathlib import Path

import superharness.modules.runner as runner_mod
from superharness.commands import continue_cmd
from superharness.engine import tasks_dao
from superharness.engine.contract_io import _task_row_from_dict
from superharness.engine.db import get_connection, init_db, transaction


def _seed(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    conn = get_connection(str(project))
    init_db(conn)
    with transaction(conn):
        for t in tasks:
            t.setdefault("project_path", project.as_posix())
            tasks_dao.upsert(conn, _task_row_from_dict(t, str(project), "2026-01-01T00:00:00Z"))
    conn.commit()
    conn.close()


# ── _pick_resumable ────────────────────────────────────────────────────────

def test_pick_resumable_prefers_in_progress_over_todo():
    tasks = [
        {"id": "a", "status": "todo"},
        {"id": "b", "status": "in_progress"},
        {"id": "c", "status": "plan_approved"},
    ]
    picked = continue_cmd._pick_resumable(tasks)
    assert picked is not None and picked["id"] == "b"


def test_pick_resumable_falls_through_priority():
    # No in_progress; plan_approved outranks report_ready and todo.
    tasks = [
        {"id": "a", "status": "todo"},
        {"id": "b", "status": "report_ready"},
        {"id": "c", "status": "plan_approved"},
    ]
    picked = continue_cmd._pick_resumable(tasks)
    assert picked["id"] == "c"


def test_pick_resumable_none_when_all_terminal():
    tasks = [
        {"id": "a", "status": "done"},
        {"id": "b", "status": "failed"},
        {"id": "c", "status": "stopped"},
    ]
    assert continue_cmd._pick_resumable(tasks) is None


# ── command behavior ─────────────────────────────────────────────────────────

def test_continue_fires_on_continue_hook_with_context(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed(project, [{"id": "feat-001", "title": "t", "status": "in_progress"}])

    calls = []
    monkeypatch.setattr(
        runner_mod, "run_hooks",
        lambda event, ctx, pdir: calls.append((event, ctx, pdir)) or [],
    )

    rc = continue_cmd.resume(str(project), json_mode=False)
    assert rc == 0

    on_continue = [c for c in calls if c[0] == "on_continue"]
    assert len(on_continue) == 1
    _, ctx, _ = on_continue[0]
    assert ctx["task_id"] == "feat-001"
    assert ctx["project_dir"] == str(project)


def test_continue_no_resumable_still_fires_hook(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed(project, [{"id": "feat-001", "title": "t", "status": "done"}])

    calls = []
    monkeypatch.setattr(
        runner_mod, "run_hooks",
        lambda event, ctx, pdir: calls.append((event, ctx, pdir)) or [],
    )

    rc = continue_cmd.resume(str(project), json_mode=False)
    assert rc == 0
    on_continue = [c for c in calls if c[0] == "on_continue"]
    assert len(on_continue) == 1
    # No task to resume → empty task_id in context.
    assert on_continue[0][1]["task_id"] == ""


def test_continue_hook_error_does_not_crash(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed(project, [{"id": "feat-001", "title": "t", "status": "in_progress"}])

    def _boom(event, ctx, pdir):
        raise RuntimeError("hook exploded")

    monkeypatch.setattr(runner_mod, "run_hooks", _boom)
    rc = continue_cmd.resume(str(project), json_mode=False)
    assert rc == 0
