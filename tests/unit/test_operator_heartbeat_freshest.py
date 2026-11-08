"""check_watcher_health must judge the watcher by its freshest heartbeat.

The watcher writes several heartbeat sources (SQLite, a legacy YAML file and
a plain-text timestamp). Taking the first source that exists let a months-old
legacy YAML shadow a fresh text heartbeat whenever SQLite had no row, which
reports a live watcher as down and makes the watchdog send a false outage
alert.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from superharness.engine import heartbeat_contract
from superharness.engine.operator import Operator


def _iso(age_seconds: int) -> str:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def harness(tmp_path, monkeypatch):
    harness_dir = tmp_path / ".superharness"
    harness_dir.mkdir()
    sqlite = {"written_at": None}
    monkeypatch.setattr(
        heartbeat_contract,
        "read_heartbeat_db",
        lambda _project, _agent="watcher": (
            SimpleNamespace(written_at=sqlite["written_at"])
            if sqlite["written_at"]
            else None
        ),
    )
    return tmp_path, harness_dir, sqlite


def _write_yaml(harness_dir, age_seconds: int) -> None:
    (harness_dir / "watcher.heartbeat.yaml").write_text(
        f"written_at: '{_iso(age_seconds)}'\n"
    )


def _write_txt(harness_dir, age_seconds: int) -> None:
    (harness_dir / "watcher.heartbeat").write_text(_iso(age_seconds))


def test_fresh_text_heartbeat_wins_over_stale_legacy_yaml(harness):
    project, harness_dir, _sqlite = harness
    _write_yaml(harness_dir, age_seconds=75 * 86400)
    _write_txt(harness_dir, age_seconds=5)

    status = Operator(project).check_watcher_health()

    assert status.is_healthy, status.message


def test_fresh_text_heartbeat_wins_over_stale_sqlite_row(harness):
    project, harness_dir, sqlite = harness
    sqlite["written_at"] = _iso(3600)
    _write_txt(harness_dir, age_seconds=5)

    status = Operator(project).check_watcher_health()

    assert status.is_healthy, status.message


def test_fresh_sqlite_row_stays_healthy_next_to_stale_files(harness):
    project, harness_dir, sqlite = harness
    sqlite["written_at"] = _iso(5)
    _write_yaml(harness_dir, age_seconds=3600)
    _write_txt(harness_dir, age_seconds=3600)

    status = Operator(project).check_watcher_health()

    assert status.is_healthy, status.message
    assert "sqlite" in status.message


def test_all_sources_stale_reports_the_freshest_age(harness):
    project, harness_dir, sqlite = harness
    sqlite["written_at"] = _iso(7200)
    _write_yaml(harness_dir, age_seconds=86400)
    _write_txt(harness_dir, age_seconds=600)

    status = Operator(project).check_watcher_health()

    assert not status.is_healthy
    age = int(status.message.split("(")[1].split("s")[0])
    assert 600 <= age < 700


def test_unparsable_source_does_not_hide_a_valid_one(harness):
    project, harness_dir, _sqlite = harness
    (harness_dir / "watcher.heartbeat.yaml").write_text("written_at: 'not a time'\n")
    _write_txt(harness_dir, age_seconds=5)

    status = Operator(project).check_watcher_health()

    assert status.is_healthy, status.message


def test_no_heartbeat_at_all_is_missing(harness):
    project, _harness_dir, _sqlite = harness

    status = Operator(project).check_watcher_health()

    assert not status.is_healthy
    assert status.message == "Heartbeat missing"
