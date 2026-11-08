"""notify must treat a missing or stale watcher heartbeat as an outage.

The launchd probe only proves the service is loaded; a hung watcher keeps
its service loaded while its heartbeat ages. Linux has no service probe at
all, so the heartbeat is the only outage signal there. An owner-disabled
operator is an intentional stop and must not alert even though its
heartbeat goes stale.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from superharness.commands import notify


@pytest.fixture
def project(tmp_path):
    project_dir = tmp_path / "proj"
    (project_dir / ".superharness").mkdir(parents=True)
    return project_dir


def _write_heartbeat(project_dir, age_seconds: int) -> None:
    ts = datetime.now(UTC) - timedelta(seconds=age_seconds)
    (project_dir / ".superharness" / "watcher.heartbeat").write_text(
        ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def test_linux_fresh_heartbeat_is_healthy(project):
    _write_heartbeat(project, age_seconds=5)

    ok, _detail = notify._watcher_health(str(project), "Linux")

    assert ok is True


def test_linux_stale_heartbeat_is_down(project):
    _write_heartbeat(project, age_seconds=3600)

    ok, detail = notify._watcher_health(str(project), "Linux")

    assert ok is False
    assert "stale" in detail.lower()


def test_linux_missing_heartbeat_is_down(project):
    ok, detail = notify._watcher_health(str(project), "Linux")

    assert ok is False
    assert "missing" in detail.lower()


def test_darwin_loaded_service_with_stale_heartbeat_is_down(project, monkeypatch):
    _write_heartbeat(project, age_seconds=3600)
    monkeypatch.setattr(
        notify, "_watcher_ok_darwin", lambda _p: (True, "op state=running exit=0")
    )

    ok, detail = notify._watcher_health(str(project), "Darwin")

    assert ok is False
    assert "stale" in detail.lower()


def test_darwin_disabled_service_ignores_stale_heartbeat(project, monkeypatch):
    _write_heartbeat(project, age_seconds=3600)
    monkeypatch.setattr(
        notify, "_watcher_ok_darwin", lambda _p: (True, "disabled by user")
    )

    ok, detail = notify._watcher_health(str(project), "Darwin")

    assert ok is True
    assert "disabled" in detail


def test_darwin_unloaded_service_is_down_even_with_fresh_heartbeat(
    project, monkeypatch
):
    _write_heartbeat(project, age_seconds=5)
    monkeypatch.setattr(
        notify, "_watcher_ok_darwin", lambda _p: (False, "op not loaded")
    )

    ok, detail = notify._watcher_health(str(project), "Darwin")

    assert ok is False
    assert "not loaded" in detail


def test_main_alerts_on_missing_heartbeat_off_macos(project, monkeypatch, capsys):
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notify, "_retry_high_ids", lambda *_a: [])

    with pytest.raises(SystemExit) as exc:
        notify.main(["-p", str(project), "--watcher-down-streak", "1", "--dry-run"])

    assert exc.value.code == 10
    assert "watcher_down:1" in capsys.readouterr().out
