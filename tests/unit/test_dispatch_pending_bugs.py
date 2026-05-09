"""
TDD tests for the 3 dispatch-pending bugs:

Bug 1: inbox.py has no __main__ block — `python -m superharness.engine.inbox
        next_pending` silently exits 0 with empty output, making YAML-path
        dispatch think there are no pending items.

Bug 2: is_sqlite_only() checks STATE_BACKEND env var, which operator never sets
        → dispatch always takes the broken YAML path.

Bug 3: operator_start calls start_stack() twice, spawning the watcher twice
        (second blocked by lock) and monitoring the wrong instance.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")

T0 = "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env():
    e = os.environ.copy()
    e["PYTHONPATH"] = SRC
    e.pop("STATE_BACKEND", None)
    return e


def _make_project(tmp_path: Path, *, task_id: str = "test-task") -> Path:
    harness = tmp_path / ".superharness"
    harness.mkdir(parents=True)
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text(
        f"id: test-contract\ntasks:\n  - id: {task_id}\n"
        f"    owner: claude-code\n    status: todo\n"
        f"    project_path: '{tmp_path.as_posix()}'\n"
    )

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao, tasks_dao

    conn = get_connection(str(tmp_path))
    init_db(conn)
    tasks_dao.upsert(conn, tasks_dao.TaskRow(
        id=task_id, title="Test", owner="claude-code", status="todo",
        version=1, created_at=T0, project_path=str(tmp_path),
        effort=None, development_method=None, acceptance_criteria=[],
        test_types=[], out_of_scope=[], definition_of_done=[],
        context=None, tdd=None,
    ))
    inbox_dao.enqueue(
        conn,
        id=f"auto-test01",
        task_id=task_id,
        target_agent="claude-code",
        priority=2,
        project_path=str(tmp_path),
        now=T0,
    )
    conn.commit()
    conn.close()
    return tmp_path


# ---------------------------------------------------------------------------
# Bug 1 — inbox.py __main__ must handle next_pending CLI call
# ---------------------------------------------------------------------------

def test_inbox_next_pending_cli_returns_item(tmp_path):
    """python -m superharness.engine.inbox next_pending must output JSON for a
    pending item, not silently exit with empty stdout."""
    _make_project(tmp_path)
    inbox_file = tmp_path / ".superharness" / "inbox.yaml"
    inbox_file.write_text(
        "# Delegation inbox\n"
        "- id: auto-test01\n"
        "  task: test-task\n"
        "  to: claude-code\n"
        "  status: pending\n"
        "  priority: 2\n"
        "  retry_count: 0\n"
        "  max_retries: 3\n"
        "  created_at: '2026-01-01T00:00:00Z'\n"
        f"  project: '{tmp_path.as_posix()}'\n"
        "  plan_only: false\n"
    )

    r = subprocess.run(
        [sys.executable, "-m", "superharness.engine.inbox", "next_pending",
         "--file", str(inbox_file), "--to", "claude-code"],
        capture_output=True, text=True, env=_env(), check=False,
    )
    assert r.returncode == 0, f"stderr: {r.stderr}"
    assert r.stdout.strip() != "", "next_pending returned empty output — items are invisible to dispatch"
    item = json.loads(r.stdout)
    assert item.get("task") == "test-task" or item.get("task_id") == "test-task"


# ---------------------------------------------------------------------------
# Bug 2 — is_sqlite_only() must return True when SQLite DB exists
# ---------------------------------------------------------------------------

def test_is_sqlite_only_true_when_db_exists(tmp_path):
    """is_sqlite_only() should return True when a SQLite DB exists in the
    project, regardless of STATE_BACKEND env var."""
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()

    env_bak = os.environ.pop("STATE_BACKEND", None)
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        result = is_sqlite_only(project_dir=str(tmp_path))
        assert result is True, (
            "is_sqlite_only() returned False even though a SQLite DB exists — "
            "dispatch falls into the broken YAML path"
        )
    finally:
        if env_bak is not None:
            os.environ["STATE_BACKEND"] = env_bak


def test_is_sqlite_only_false_when_no_db(tmp_path):
    """is_sqlite_only() must return False when no SQLite DB exists (no DB = YAML mode)."""
    (tmp_path / ".superharness").mkdir()
    env_bak = os.environ.pop("STATE_BACKEND", None)
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        assert is_sqlite_only(project_dir=str(tmp_path)) is False
    finally:
        if env_bak is not None:
            os.environ["STATE_BACKEND"] = env_bak


# ---------------------------------------------------------------------------
# Bug 3 — operator_start must call start_stack exactly once
# ---------------------------------------------------------------------------

def test_operator_start_calls_start_stack_once(tmp_path):
    """operator_start must call start_stack() exactly once, not twice.
    Calling it twice spawns the watcher twice (second blocked by lock) and
    monitor_and_recover tracks the wrong Operator instance."""
    (tmp_path / ".superharness").mkdir()

    call_count = []

    class FakeOperator:
        def __init__(self, project):
            self.project = project
            self.processes = {}

        def start_stack(self, dashboard_port=8787, no_open=False):
            call_count.append(1)

        def monitor_and_recover(self):
            raise SystemExit(0)  # stop the loop

    from superharness.engine import operator as op_module
    original_cls = op_module.Operator

    with patch.object(op_module, "Operator", FakeOperator):
        from superharness.cli import operator as operator_group
        # Find the 'start' command function
        start_cmd = None
        for cmd_name, cmd_obj in operator_group.commands.items():
            if cmd_name == "start":
                start_cmd = cmd_obj
                break
        assert start_cmd is not None

        from click.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(start_cmd, ["--project", str(tmp_path), "--no-open"])

    assert len(call_count) == 1, (
        f"start_stack() was called {len(call_count)} times — expected exactly 1. "
        "Duplicate calls spawn the watcher twice and monitor the wrong instance."
    )


# ---------------------------------------------------------------------------
# Bug 4 — dispatch must pass project_dir to is_sqlite_only()
# ---------------------------------------------------------------------------

def test_dispatch_passes_project_dir_to_is_sqlite_only(tmp_path, monkeypatch):
    """inbox_dispatch must call is_sqlite_only(project_dir=project_dir).
    Calling is_sqlite_only() without project_dir returns False (when
    STATE_BACKEND is unset), making dispatch fall to the broken YAML
    path even though SQLite is the source of truth."""
    project = _make_project(tmp_path)
    # No STATE_BACKEND env, no inbox.yaml — only SQLite.
    monkeypatch.delenv("STATE_BACKEND", raising=False)
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    # The call must include project_dir keyword
    assert "is_sqlite_only(project_dir=project_dir)" in src or \
           "is_sqlite_only(project_dir=" in src, (
        "inbox_dispatch.py must call is_sqlite_only(project_dir=...) — "
        "calling without an arg returns False and dispatch silently uses "
        "the YAML path even when SQLite is the only source of truth."
    )


# ---------------------------------------------------------------------------
# Bug 5 — auto_dispatch must import uuid and pass project_dir to classify_task
# ---------------------------------------------------------------------------

def test_auto_dispatch_imports_uuid_and_passes_project_dir(tmp_path):
    """auto_dispatch.py must import uuid (for item_id generation) and pass
    project_dir to classify_task (so the router can load project-specific
    model maps)."""
    from superharness.commands.auto_dispatch import _classify_task, _enqueue
    from unittest.mock import patch

    # 1. Verify uuid import (by attempting to enqueue)
    _make_project(tmp_path, task_id="task-uuid")
    with patch("superharness.engine.inbox_dao.enqueue") as mock_enqueue:
        # This calls uuid.uuid4(). If uuid is not imported, it raises NameError.
        _enqueue(str(tmp_path), "task-uuid", "claude-code")
        assert mock_enqueue.called

    # 2. Verify project_dir pass to classify_task
    task = {"title": "Test", "id": "t1"}
    with patch("superharness.engine.model_router.classify_task") as mock_classify:
        mock_classify.return_value = ("mini", "low")
        _classify_task(task, str(tmp_path))
        # Ensure project_dir was passed as keyword arg
        kwargs = mock_classify.call_args.kwargs
        assert kwargs.get("project_dir") == str(tmp_path), (
            "auto_dispatch._classify_task must pass project_dir to classify_task "
            "to support project-specific model mappings."
        )
