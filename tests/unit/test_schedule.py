"""Tests for shux schedule — cron-like scheduled dispatch (Phase 5)."""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text(yaml.dump({
        "id": "test", "created": "2026-01-01", "created_by": "agent",
        "status": "active", "tasks": [],
    }))
    return project


# ===========================================================================
# Cron parser
# ===========================================================================


class TestCronParser:
    def test_wildcard_fields(self):
        from superharness.commands.schedule import _parse_cron
        p = _parse_cron("* * * * *")
        assert all(v is None for v in p.values())

    def test_specific_values(self):
        from superharness.commands.schedule import _parse_cron
        p = _parse_cron("30 9 1 6 1")
        assert p["minute"] == 30
        assert p["hour"] == 9
        assert p["dom"] == 1
        assert p["month"] == 6
        assert p["dow"] == 1

    def test_wrong_field_count_raises(self):
        from superharness.commands.schedule import _parse_cron
        with pytest.raises(ValueError, match="5 fields"):
            _parse_cron("* * *")

    def test_out_of_range_raises(self):
        from superharness.commands.schedule import _parse_cron
        with pytest.raises(ValueError, match="out of range"):
            _parse_cron("60 * * * *")  # minute 60 is invalid

    def test_non_integer_raises(self):
        from superharness.commands.schedule import _parse_cron
        with pytest.raises(ValueError, match="integer"):
            _parse_cron("*/5 * * * *")  # step syntax not supported


# ===========================================================================
# next_run calculation
# ===========================================================================


class TestNextRun:
    def test_every_minute_advances_one_minute(self):
        from superharness.commands.schedule import _next_run
        after = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
        nxt = _next_run("* * * * *", after)
        assert nxt == datetime(2026, 1, 1, 9, 1, tzinfo=timezone.utc)

    def test_specific_hour_minute(self):
        from superharness.commands.schedule import _next_run
        after = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)
        nxt = _next_run("30 9 * * *", after)
        assert nxt.hour == 9
        assert nxt.minute == 30

    def test_wraps_to_next_day(self):
        from superharness.commands.schedule import _next_run
        after = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        nxt = _next_run("30 9 * * *", after)
        assert nxt.day == 2  # next day since 09:30 on Jan 1 has passed

    def test_always_strictly_after(self):
        from superharness.commands.schedule import _next_run
        after = datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc)
        nxt = _next_run("30 9 * * *", after)
        assert nxt > after


# ===========================================================================
# cmd_add / cmd_list / cmd_remove
# ===========================================================================


class TestScheduleCRUD:
    def test_add_creates_schedule(self, tmp_path):
        from superharness.commands.schedule import cmd_add, _load_schedules, _scheduled_path
        project = _make_project(tmp_path)
        rc = cmd_add(str(project), "T-1", "0 9 * * *")
        assert rc == 0
        schedules = _load_schedules(_scheduled_path(str(project)))
        assert len(schedules) == 1
        assert schedules[0]["task_id"] == "T-1"
        assert schedules[0]["cron"] == "0 9 * * *"
        assert "next_run" in schedules[0]

    def test_add_updates_existing(self, tmp_path):
        from superharness.commands.schedule import cmd_add, _load_schedules, _scheduled_path
        project = _make_project(tmp_path)
        cmd_add(str(project), "T-1", "0 9 * * *")
        cmd_add(str(project), "T-1", "0 10 * * *")
        schedules = _load_schedules(_scheduled_path(str(project)))
        assert len(schedules) == 1
        assert schedules[0]["cron"] == "0 10 * * *"

    def test_add_invalid_cron_returns_1(self, tmp_path):
        from superharness.commands.schedule import cmd_add
        project = _make_project(tmp_path)
        rc = cmd_add(str(project), "T-1", "bad cron expression")
        assert rc == 1

    def test_add_with_agent(self, tmp_path):
        from superharness.commands.schedule import cmd_add, _load_schedules, _scheduled_path
        project = _make_project(tmp_path)
        cmd_add(str(project), "T-2", "* * * * *", agent="codex-cli")
        schedules = _load_schedules(_scheduled_path(str(project)))
        assert schedules[0]["agent"] == "codex-cli"

    def test_list_empty(self, tmp_path, capsys):
        from superharness.commands.schedule import cmd_list
        project = _make_project(tmp_path)
        rc = cmd_list(str(project))
        assert rc == 0
        assert "No schedules" in capsys.readouterr().out

    def test_list_shows_entries(self, tmp_path, capsys):
        from superharness.commands.schedule import cmd_add, cmd_list
        project = _make_project(tmp_path)
        cmd_add(str(project), "T-3", "30 8 * * 1")
        rc = cmd_list(str(project))
        assert rc == 0
        out = capsys.readouterr().out
        assert "T-3" in out
        assert "30 8 * * 1" in out

    def test_remove_existing(self, tmp_path):
        from superharness.commands.schedule import cmd_add, cmd_remove, _load_schedules, _scheduled_path
        project = _make_project(tmp_path)
        cmd_add(str(project), "T-4", "* * * * *")
        rc = cmd_remove(str(project), "T-4")
        assert rc == 0
        schedules = _load_schedules(_scheduled_path(str(project)))
        assert schedules == []

    def test_remove_missing_returns_1(self, tmp_path):
        from superharness.commands.schedule import cmd_remove
        project = _make_project(tmp_path)
        rc = cmd_remove(str(project), "T-nonexistent")
        assert rc == 1


# ===========================================================================
# cmd_run — dry-run and live enqueue
# ===========================================================================


class TestScheduleRun:
    def _write_schedule(self, project: Path, task_id: str, next_run: str) -> None:
        from superharness.commands.schedule import _scheduled_path
        path = _scheduled_path(str(project))
        data = {"schedules": [{
            "task_id": task_id,
            "cron": "* * * * *",
            "next_run": next_run,
            "enqueue_count": 0,
            "agent": None,
        }]}
        import yaml
        with open(path, "w") as f:
            yaml.dump(data, f)

    def test_dry_run_does_not_enqueue(self, tmp_path, capsys):
        from superharness.commands.schedule import cmd_run
        project = _make_project(tmp_path)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._write_schedule(project, "T-10", past)
        with patch("superharness.commands.schedule.inbox_enqueue") as mock_enqueue:
            rc = cmd_run(str(project), dry_run=True)
        assert mock_enqueue.main.call_count == 0
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out

    def test_future_schedule_not_enqueued(self, tmp_path):
        from superharness.commands.schedule import cmd_run
        project = _make_project(tmp_path)
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._write_schedule(project, "T-11", future)
        with patch("superharness.commands.schedule.inbox_enqueue") as mock_enqueue:
            cmd_run(str(project), dry_run=False)
        mock_enqueue.main.assert_not_called()

    def test_due_schedule_enqueued(self, tmp_path, capsys):
        from superharness.commands.schedule import cmd_run, _load_schedules, _scheduled_path
        project = _make_project(tmp_path)
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._write_schedule(project, "T-12", past)
        with patch("superharness.commands.schedule.inbox_enqueue") as mock_enqueue:
            mock_enqueue.main.return_value = 0
            rc = cmd_run(str(project), dry_run=False)
        assert rc == 0
        mock_enqueue.main.assert_called_once()
        # next_run should have advanced
        schedules = _load_schedules(_scheduled_path(str(project)))
        new_next = schedules[0]["next_run"]
        assert new_next > past
        assert schedules[0]["enqueue_count"] == 1

    def test_no_schedules_returns_0(self, tmp_path):
        from superharness.commands.schedule import cmd_run
        project = _make_project(tmp_path)
        rc = cmd_run(str(project), dry_run=False)
        assert rc == 0
