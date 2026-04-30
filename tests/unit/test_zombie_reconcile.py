"""Tests for zombie inbox item reconciliation.

Unit tests: _reconcile_zombies function directly.
Integration test: _run_scripts calls _reconcile_zombies during watcher cycle.
E2E test: inbox_watch --once reconciles zombies end-to-end.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import yaml

PYTHON = sys.executable


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "handoffs").mkdir()
    seed_sqlite_from_yaml(project)
    return project


def _write_contract(project: Path, tasks: list[dict]) -> None:
    harness = project / ".superharness"
    doc = {"id": "test", "tasks": tasks}
    (harness / "contract.yaml").write_text(yaml.dump(doc))


def _write_inbox(project: Path, items: list[dict]) -> None:
    harness = project / ".superharness"
    lines = ["# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n"]
    (harness / "inbox.yaml").write_text(lines[0] + yaml.dump(items))


def _read_inbox(project: Path) -> list[dict]:
    harness = project / ".superharness"
    return yaml.safe_load((harness / "inbox.yaml").read_text()) or []


class TestReconcileZombies:
    """Test _reconcile_zombies in inbox_watch.py."""

    def test_launched_contract_done_reconciles_to_done(self, tmp_path):
        """Inbox launched + contract done → inbox marked done."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "done", "owner": "claude-code"}])
        _write_inbox(project, [
            {"id": "item1", "task": "t1", "to": "claude-code", "status": "launched",
             "launched_at": "2026-03-20T10:00:00Z", "project": str(project)},
        ])

        count = _reconcile_zombies(str(project))
        assert count == 1
        items = _read_inbox(project)
        assert items[0]["status"] == "done"

    def test_launched_with_dead_pid_marks_failed(self, tmp_path):
        """Inbox launched + PID not alive → inbox marked failed."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "todo", "owner": "claude-code"}])
        _write_inbox(project, [
            {"id": "item1", "task": "t1", "to": "claude-code", "status": "launched",
             "pid": "999999", "launched_at": "2026-03-20T10:00:00Z", "project": str(project)},
        ])

        count = _reconcile_zombies(str(project))
        assert count == 1
        items = _read_inbox(project)
        assert items[0]["status"] == "failed"

    def test_launched_with_live_pid_not_touched(self, tmp_path):
        """Inbox launched + PID alive → not touched."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "todo", "owner": "claude-code"}])
        # Use our own PID (guaranteed alive)
        _write_inbox(project, [
            {"id": "item1", "task": "t1", "to": "claude-code", "status": "launched",
             "pid": str(os.getpid()), "launched_at": "2026-03-20T10:00:00Z", "project": str(project)},
        ])

        count = _reconcile_zombies(str(project))
        assert count == 0
        items = _read_inbox(project)
        assert items[0]["status"] == "launched"

    def test_launched_no_pid_old_marks_failed(self, tmp_path):
        """Inbox launched + no PID + old → inbox marked failed."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "todo", "owner": "claude-code"}])
        _write_inbox(project, [
            {"id": "item1", "task": "t1", "to": "claude-code", "status": "launched",
             "launched_at": "2026-01-01T00:00:00Z", "project": str(project)},
        ])

        count = _reconcile_zombies(str(project), max_age_seconds=60)
        assert count == 1
        items = _read_inbox(project)
        assert items[0]["status"] == "failed"

    def test_launched_no_pid_recent_not_touched(self, tmp_path):
        """Inbox launched + no PID + recent → not touched (might still be starting)."""
        from superharness.commands.inbox_watch import _reconcile_zombies
        from datetime import datetime, timezone

        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "todo", "owner": "claude-code"}])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        _write_inbox(project, [
            {"id": "item1", "task": "t1", "to": "claude-code", "status": "launched",
             "launched_at": now, "project": str(project)},
        ])

        count = _reconcile_zombies(str(project), max_age_seconds=3600)
        assert count == 0
        items = _read_inbox(project)
        assert items[0]["status"] == "launched"

    def test_pending_and_done_items_not_touched(self, tmp_path):
        """Only launched items are checked."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = _make_project(tmp_path)
        _write_contract(project, [
            {"id": "t1", "status": "done", "owner": "claude-code"},
            {"id": "t2", "status": "todo", "owner": "claude-code"},
        ])
        _write_inbox(project, [
            {"id": "item1", "task": "t1", "to": "claude-code", "status": "done",
             "project": str(project)},
            {"id": "item2", "task": "t2", "to": "claude-code", "status": "pending",
             "project": str(project)},
        ])

        count = _reconcile_zombies(str(project))
        assert count == 0


# ---------------------------------------------------------------------------
# Integration: _run_scripts calls _reconcile_zombies
# ---------------------------------------------------------------------------

class TestReconcileIntegration:
    """Verify _run_scripts integrates zombie reconciliation."""

    def test_run_scripts_reconciles_zombie(self, tmp_path, monkeypatch):
        """_run_scripts reconciles a launched+contract-done zombie during watcher cycle."""
        from superharness.commands import inbox_watch

        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "done", "owner": "claude-code"}])
        _write_inbox(project, [
            {"id": "zombie1", "task": "t1", "to": "claude-code", "status": "launched",
             "launched_at": "2026-03-20T10:00:00Z", "project": str(project)},
        ])
        (project / ".superharness" / "ledger.md").write_text("")

        # Stub out everything except reconciliation
        monkeypatch.setattr(inbox_watch, "_sync_worker_copy", lambda p: None)
        monkeypatch.setattr(inbox_watch, "_find_scripts_dir", lambda: str(project))
        monkeypatch.setattr(inbox_watch, "_run_dispatch_cmd", lambda **kw: None)

        inbox_watch._run_scripts(
            str(project),
            target="claude-code",
            print_only=True,
            non_interactive=False,
            codex_bypass=False,
            launcher_timeout=0,
            recover_timeout_minutes=20,
            recover_action="stale",
        )

        items = _read_inbox(project)
        assert items[0]["status"] == "done"


# ---------------------------------------------------------------------------
# E2E: inbox_watch --once reconciles zombies
# ---------------------------------------------------------------------------

class TestReconcileE2E:
    """End-to-end: run inbox_watch --once and verify zombie reconciliation."""

    def test_watch_once_reconciles_contract_done_zombie(self, tmp_path):
        """inbox_watch --once reconciles launched item when contract says done."""
        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "done", "owner": "claude-code"}])
        _write_inbox(project, [
            {"id": "zombie1", "task": "t1", "to": "claude-code", "status": "launched",
             "launched_at": "2026-03-20T10:00:00Z", "project": str(project)},
        ])
        (project / ".superharness" / "ledger.md").write_text("")

        env = os.environ.copy()
        env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"
        r = subprocess.run(
            [PYTHON, "-m", "superharness.commands.inbox_watch",
             "--project", str(project), "--once", "--to", "claude-code", "--print-only"],
            capture_output=True, text=True, check=False, env=env,
            timeout=30,
        )

        items = _read_inbox(project)
        assert items[0]["status"] == "done", f"Expected done, got {items[0]['status']}. stderr: {r.stderr}"

    def test_watch_once_reconciles_dead_pid_zombie(self, tmp_path):
        """inbox_watch --once marks launched item failed when PID is dead."""
        project = _make_project(tmp_path)
        _write_contract(project, [{"id": "t1", "status": "todo", "owner": "claude-code"}])
        _write_inbox(project, [
            {"id": "zombie1", "task": "t1", "to": "claude-code", "status": "launched",
             "pid": "999999", "launched_at": "2026-03-20T10:00:00Z", "project": str(project)},
        ])
        (project / ".superharness" / "ledger.md").write_text("")

        env = os.environ.copy()
        env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"
        r = subprocess.run(
            [PYTHON, "-m", "superharness.commands.inbox_watch",
             "--project", str(project), "--once", "--to", "claude-code", "--print-only"],
            capture_output=True, text=True, check=False, env=env,
            timeout=30,
        )

        items = _read_inbox(project)
        assert items[0]["status"] == "failed", f"Expected failed, got {items[0]['status']}. stderr: {r.stderr}"
