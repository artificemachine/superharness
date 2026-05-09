"""Regression tests for _reconcile_zombies() max-age cap (Check 2c).

Before the fix, launched items with an alive PID and no plan_only flag
could run indefinitely — no wall-clock cap existed. A 406-minute orphaned
discussion item was the observed failure.

After the fix, any non-plan-only launched item with a live PID running
beyond _MAX_LAUNCH_AGE_SECONDS (7200s / 2h) is killed and marked failed.
"""
from __future__ import annotations

import os
import sys
import signal
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parents[2] / "src"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_contract(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text(
        yaml.dump({"id": "test-contract", "tasks": tasks}, default_flow_style=False)
    )


def _write_inbox(project: Path, items: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "inbox.yaml").write_text(
        yaml.dump(items, default_flow_style=False)
    )


def _launched_item(
    item_id: str,
    task_id: str,
    pid: int,
    age_hours: float,
    plan_only: bool = False,
) -> dict:
    launched_at = (
        datetime.now(timezone.utc) - timedelta(hours=age_hours)
    ).isoformat()
    return {
        "id": item_id,
        "task": task_id,
        "status": "launched",
        "target_agent": "claude-code",
        "pid": str(pid),
        "launched_at": launched_at,
        "plan_only": plan_only,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestReconcileZombieMaxAge:
    """Check 2c: non-plan-only items with alive PID but age > 2h get failed."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_max_age_exceeded_kills_and_fails(self, tmp_path):
        """Item running 3h with alive PID gets killed and marked failed."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()

        fake_pid = 99999
        item = _launched_item("long-001", "slow-task", fake_pid, age_hours=3.0)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "slow-task", "owner": "claude-code", "status": "in_progress"},
        ])

        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=True), \
             patch("os.kill") as mock_kill, \
             patch("superharness.engine.db.get_connection", return_value=MagicMock()), \
             patch("superharness.engine.db.init_db"), \
             patch("superharness.engine.inbox_dao.get", return_value=None), \
             patch("superharness.engine.inbox_dao.update_status"):
            reconciled = _reconcile_zombies(str(project))

        assert reconciled >= 1
        mock_kill.assert_called_once_with(fake_pid, signal.SIGTERM)

    def test_within_max_age_not_failed(self, tmp_path):
        """Item running 1h with alive PID must NOT be failed (within 2h cap)."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()

        fake_pid = 99998
        item = _launched_item("short-001", "active-task", fake_pid, age_hours=1.0)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "active-task", "owner": "claude-code", "status": "in_progress"},
        ])

        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=True), \
             patch("os.kill") as mock_kill:
            reconciled = _reconcile_zombies(str(project))

        assert reconciled == 0
        mock_kill.assert_not_called()

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_plan_only_uses_15min_cap_not_2h(self, tmp_path):
        """plan_only items use the 15-min cap (Check 2b), not the 2h cap (Check 2c)."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()

        fake_pid = 99997
        # 20 min old plan-only → should be caught by Check 2b (15 min cap)
        item = _launched_item("plan-001", "plan-task", fake_pid,
                              age_hours=0.34, plan_only=True)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "plan-task", "owner": "claude-code", "status": "plan_approved"},
        ])

        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=True), \
             patch("os.kill") as mock_kill, \
             patch("superharness.engine.db.get_connection", return_value=MagicMock()), \
             patch("superharness.engine.db.init_db"), \
             patch("superharness.engine.inbox_dao.get", return_value=None), \
             patch("superharness.engine.inbox_dao.update_status"):
            reconciled = _reconcile_zombies(str(project))

        assert reconciled >= 1
        mock_kill.assert_called_once_with(fake_pid, signal.SIGTERM)

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_dead_pid_still_fails_regardless_of_age(self, tmp_path):
        """Dead PID path (Check 2) still fires regardless of age — not affected by 2c."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()

        fake_pid = 99996
        item = _launched_item("dead-001", "dead-task", fake_pid, age_hours=0.1)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "dead-task", "owner": "claude-code", "status": "in_progress"},
        ])

        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=False), \
             patch("superharness.engine.db.get_connection", return_value=MagicMock()), \
             patch("superharness.engine.db.init_db"), \
             patch("superharness.engine.inbox_dao.get", return_value=None), \
             patch("superharness.engine.inbox_dao.update_status"):
            reconciled = _reconcile_zombies(str(project))

        assert reconciled >= 1
