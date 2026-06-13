"""Regression test: close_task fires the on_close module hook.

Bug (pre-fix): close.py imported a phantom `_vault_write_task_done` from
superharness.commands.task that never existed in the entire git history. The
ImportError was swallowed by a bare `except Exception`, so vault sync silently
failed on every task close. The fix routes vault sync through the module
system's `on_close` lifecycle event (the design already declared in
module_templates/obsidian.yaml), which is the correct, opt-in home for it.

This test pins the contract: closing a task fires exactly one `on_close` hook
with a context the obsidian action understands (task_id, summary, project_name,
actor). It does not assert a vault write — that is module-gated and opt-in.
"""
from __future__ import annotations

from pathlib import Path

import superharness.modules.runner as runner_mod
from superharness.commands import close as close_mod
from superharness.engine import tasks_dao
from superharness.engine.contract_io import _task_row_from_dict
from superharness.engine.db import get_connection, init_db, transaction


def _seed_report_ready_task(project: Path) -> None:
    (project / ".superharness" / "handoffs").mkdir(parents=True, exist_ok=True)
    task_dict = {
        "id": "feat-001",
        "title": "Build feature one",
        "owner": "claude-code",
        "status": "report_ready",
        "project_path": project.as_posix(),
        "verified": True,
        "verified_at": "2026-03-15T00:00:00Z",
        "verified_by": "claude-code",
    }
    conn = get_connection(str(project))
    init_db(conn)
    with transaction(conn):
        tasks_dao.upsert(
            conn, _task_row_from_dict(task_dict, str(project), "2026-01-01T00:00:00Z")
        )
    conn.commit()
    conn.close()


def test_close_fires_on_close_hook(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    _seed_report_ready_task(project)

    calls: list[tuple] = []

    def _spy(event, context, project_dir):
        calls.append((event, context, project_dir))
        return []

    monkeypatch.setattr(runner_mod, "run_hooks", _spy)

    rc = close_mod.close_task(
        project_dir=str(project),
        task_id="feat-001",
        actor="claude-code",
        summary="done summary",
    )
    assert rc == 0

    on_close = [c for c in calls if c[0] == "on_close"]
    assert len(on_close) == 1, f"expected exactly one on_close hook, got {calls!r}"

    _, ctx, pdir = on_close[0]
    assert ctx["task_id"] == "feat-001"
    assert ctx["summary"] == "done summary"
    assert ctx["actor"] == "claude-code"
    assert ctx["project_name"] == "proj"
    assert str(pdir) == str(project)


def test_close_has_no_phantom_vault_import():
    """The dead `_vault_write_task_done` must not be imported or called.

    A mention in a comment is allowed (it documents the bug); an actual import
    or call is the regression we guard against.
    """
    import inspect

    src = inspect.getsource(close_mod)
    assert "import _vault_write_task_done" not in src
    assert "_vault_write_task_done(" not in src
