"""Regression tests for BUG-2026-09-24-operator-start-reports-stale-before-first-cycle.

Defect 1: `shux status` run within the watcher's first cycle after
`shux operator start` reported the previous run's stale heartbeat as a dead
watcher and prescribed `shux operator start`, the command just run.

Defect 2: `shux operator start` printed and recorded the pid of the parent
process, which exits right after the fork, so the printed "monitor pid" was
dead and operator-state.json named a dead operator.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from superharness.engine.operator import _OPERATOR_STATE_FILE, Operator

_CHILD_PID = 4242


def _project(tmp_path: Path) -> Path:
    (tmp_path / ".superharness").mkdir()
    return tmp_path


def _write_stale_legacy_heartbeat(project: Path, minutes_old: int) -> None:
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    hb = project / ".superharness" / "watcher.heartbeat"
    hb.write_text(ts.strftime("%Y-%m-%dT%H:%M:%SZ") + "\n")


def _write_operator_state(project: Path, pid: int, started_ago: float) -> None:
    state = project / _OPERATOR_STATE_FILE
    state.write_text(
        json.dumps({"operator_pid": pid, "operator_started_at": time.time() - started_ago})
    )


def _empty_health():
    inbox_health = {
        "counts": {},
        "orphaned": [],
        "duplicates": {},
        "stale_pending": [],
        "stale_launched": [],
        "dead_pid": [],
        "discussion_orphans": [],
        "missing_task": [],
        "stale_items": [],
    }
    disc_health = {"counts": {}, "consensus_unclosed": [], "stale_active": []}
    task_health = {
        "counts": {},
        "no_timestamp": [],
        "stuck_inprogress": [],
        "stuck_plan": [],
        "stuck_noreview": [],
        "stuck_waiting": [],
    }
    return inbox_health, disc_health, task_health


# ---------------------------------------------------------------------------
# Defect 1: first-cycle window
# ---------------------------------------------------------------------------


def test_stale_heartbeat_within_first_cycle_reports_starting(tmp_path):
    from superharness.commands.status import _heartbeat_status

    project = _project(tmp_path)
    _write_stale_legacy_heartbeat(project, minutes_old=3304)
    _write_operator_state(project, pid=os.getpid(), started_ago=3)

    level, detail = _heartbeat_status(str(project), str(project / ".superharness"))

    assert level == "starting", f"got {level}: {detail}"
    assert "first watcher cycle" in detail


def test_missing_heartbeat_within_first_cycle_reports_starting(tmp_path):
    from superharness.commands.status import _heartbeat_status

    project = _project(tmp_path)
    _write_operator_state(project, pid=os.getpid(), started_ago=3)

    level, _detail = _heartbeat_status(str(project), str(project / ".superharness"))

    assert level == "starting"


def test_stale_heartbeat_after_grace_window_stays_stale(tmp_path):
    from superharness.commands.status import _heartbeat_status

    project = _project(tmp_path)
    _write_stale_legacy_heartbeat(project, minutes_old=3304)
    _write_operator_state(project, pid=os.getpid(), started_ago=600)

    level, _detail = _heartbeat_status(str(project), str(project / ".superharness"))

    assert level == "stale"


def test_recent_start_with_dead_operator_stays_stale(tmp_path):
    from superharness.commands.status import _heartbeat_status

    project = _project(tmp_path)
    _write_stale_legacy_heartbeat(project, minutes_old=3304)
    _write_operator_state(project, pid=99999999, started_ago=3)

    level, _detail = _heartbeat_status(str(project), str(project / ".superharness"))

    assert level == "stale"


def test_starting_heartbeat_does_not_prescribe_operator_start():
    from superharness.commands.status import _collect_issues

    inbox_health, disc_health, task_health = _empty_health()

    issues, fixes = _collect_issues(
        "/tmp/proj",
        "ok",
        "starting",
        "starting",
        "operator started 3s ago, first watcher cycle pending",
        inbox_health,
        disc_health,
        task_health,
    )

    assert "shux operator start" not in fixes
    assert issues == []


# ---------------------------------------------------------------------------
# Defect 2: printed and recorded pid
# ---------------------------------------------------------------------------


def _start_stack_state_only(self, dashboard_port=8787, no_open=False, use_dashboard=False):
    self._use_dashboard = use_dashboard
    self._write_daemon_info(dashboard_port)


def test_operator_start_prints_and_records_the_daemon_pid(tmp_path):
    from superharness.cli import main

    project = _project(tmp_path)
    with (
        patch("superharness.cli._resume_installed_operator", return_value=False),
        patch.object(Operator, "start_stack", _start_stack_state_only),
        # create=True: Windows has no os.fork; the test drives the parent
        # side of the fork on every platform.
        patch("superharness.cli.os.fork", return_value=_CHILD_PID, create=True),
    ):
        result = CliRunner().invoke(main, ["operator", "start", "--project", str(project)])

    assert result.exit_code == 0, result.output
    assert f"monitor pid: {os.getpid()}" not in result.output
    assert f"monitor pid: {_CHILD_PID}" in result.output
    state = json.loads((project / _OPERATOR_STATE_FILE).read_text())
    assert state["operator_pid"] == _CHILD_PID
