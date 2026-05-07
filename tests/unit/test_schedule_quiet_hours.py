"""Tests for schedule quiet-hours support — Phase 3 heartbeat exclude windows."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest


# ---------------------------------------------------------------------------
# _in_quiet_window helper
# ---------------------------------------------------------------------------

def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 5, 1, hour, minute, 0, tzinfo=timezone.utc)


def test_in_quiet_window_inside_day_window():
    from superharness.commands.schedule import _in_quiet_window
    # 09:00–17:00, check 12:00
    assert _in_quiet_window(_utc(12), [{"start": "09:00", "end": "17:00"}]) is True


def test_in_quiet_window_outside_day_window():
    from superharness.commands.schedule import _in_quiet_window
    # 09:00–17:00, check 08:59
    assert _in_quiet_window(_utc(8, 59), [{"start": "09:00", "end": "17:00"}]) is False


def test_in_quiet_window_end_boundary_exclusive():
    from superharness.commands.schedule import _in_quiet_window
    # 09:00–17:00, check 17:00 (should be outside)
    assert _in_quiet_window(_utc(17, 0), [{"start": "09:00", "end": "17:00"}]) is False


def test_in_quiet_window_overnight_inside():
    from superharness.commands.schedule import _in_quiet_window
    # 22:00–06:00, check 23:30
    assert _in_quiet_window(_utc(23, 30), [{"start": "22:00", "end": "06:00"}]) is True


def test_in_quiet_window_overnight_early_morning():
    from superharness.commands.schedule import _in_quiet_window
    # 22:00–06:00, check 03:00
    assert _in_quiet_window(_utc(3), [{"start": "22:00", "end": "06:00"}]) is True


def test_in_quiet_window_overnight_outside():
    from superharness.commands.schedule import _in_quiet_window
    # 22:00–06:00, check 10:00
    assert _in_quiet_window(_utc(10), [{"start": "22:00", "end": "06:00"}]) is False


def test_in_quiet_window_no_windows_returns_false():
    from superharness.commands.schedule import _in_quiet_window
    assert _in_quiet_window(_utc(12), []) is False
    assert _in_quiet_window(_utc(12), None) is False


def test_in_quiet_window_multiple_windows_first_matches():
    from superharness.commands.schedule import _in_quiet_window
    windows = [
        {"start": "01:00", "end": "03:00"},
        {"start": "13:00", "end": "15:00"},
    ]
    assert _in_quiet_window(_utc(14), windows) is True
    assert _in_quiet_window(_utc(12), windows) is False


def test_in_quiet_window_malformed_entry_skipped():
    from superharness.commands.schedule import _in_quiet_window
    # Malformed entry should not crash — just skip
    windows = [{"start": "bad", "end": "worse"}, {"start": "10:00", "end": "12:00"}]
    assert _in_quiet_window(_utc(11), windows) is True


# ---------------------------------------------------------------------------
# cmd_run respects quiet hours
# ---------------------------------------------------------------------------

def test_cmd_run_quiet_window_suppresses_dispatch(tmp_path):
    from superharness.commands.schedule import cmd_run, _in_quiet_window
    from unittest.mock import patch
    import yaml

    sh = tmp_path / ".superharness"
    sh.mkdir()
    scheduled = {
        "schedules": [
            {
                "task_id": "t1",
                "cron": "* * * * *",
                "next_run": "2026-01-01T00:00:00Z",
                "enqueue_count": 0,
            }
        ]
    }
    (sh / "scheduled.yaml").write_text(yaml.dump(scheduled))

    # Patch _now_utc to return a time inside the quiet window
    with patch("superharness.commands.schedule._now_utc",
               return_value=datetime(2026, 1, 1, 23, 0, 0, tzinfo=timezone.utc)):
        with patch("superharness.commands.schedule.inbox_enqueue") as mock_enqueue:
            rc = cmd_run(
                str(tmp_path),
                dry_run=False,
                quiet_hours=[{"start": "22:00", "end": "06:00"}],
            )

    mock_enqueue.main.assert_not_called()
    assert rc == 0
