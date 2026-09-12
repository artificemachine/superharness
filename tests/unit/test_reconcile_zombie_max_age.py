"""Regression tests for _reconcile_zombies() max-age cap (Check 2c).

Before the fix, launched items with an alive PID and no plan_only flag
could run indefinitely — no wall-clock cap existed. A 406-minute orphaned
discussion item was the observed failure.

After the fix, any non-plan-only launched item with a live PID running
beyond _MAX_LAUNCH_AGE_SECONDS (7200s / 2h) is killed and marked failed.
"""

from __future__ import annotations

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
    launched_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
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


    def test_within_max_age_not_failed(self, tmp_path):
        """Item running 1h with alive PID must NOT be failed (within 2h cap)."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()

        fake_pid = 99998
        item = _launched_item("short-001", "active-task", fake_pid, age_hours=1.0)
        _write_inbox(project, [item])
        _write_contract(
            project,
            [
                {"id": "active-task", "owner": "claude-code", "status": "in_progress"},
            ],
        )

        with (
            patch(
                "superharness.commands.inbox_watch._pid_is_running", return_value=True
            ),
            patch("os.kill") as mock_kill,
        ):
            reconciled = _reconcile_zombies(str(project))

        assert reconciled == 0
        mock_kill.assert_not_called()


