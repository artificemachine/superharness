"""shux doctor reports automation health from the same classification as
the watchdog and `shux notify`, plus the watchdog's own last-run receipt.

- `ai_driven` being configured is not the same as automation running:
  doctor says which one holds.
- On macOS a missing, stale or failing watchdog receipt is a warning,
  because the watchdog cannot report its own death.
- The last delivered alert and an open outage are shown.
"""

from __future__ import annotations

import time

import pytest

from superharness.commands import doctor, notify
from superharness.engine import launchd_health


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / ".superharness").mkdir()
    monkeypatch.setattr(
        "superharness.commands.doctor._operator_launchd_status",
        lambda project_dir: ("com.superharness.operator.test1234", True),
    )
    return tmp_path


def _doctor_lines(capsys, project) -> list[str]:
    try:
        doctor.main(["--project", str(project)])
    except SystemExit:
        # A bare tmp project fails unrelated checks; the lines are printed first.
        pass
    return capsys.readouterr().out.splitlines()


def _line(lines, prefix) -> str:
    match = [line for line in lines if line.split(" ", 1)[-1].startswith(prefix)]
    assert match, f"no '{prefix}' line in doctor output:\n" + "\n".join(lines)
    return match[0]


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr("superharness.commands.doctor.platform.system", lambda: "Linux")


@pytest.fixture
def darwin(monkeypatch):
    monkeypatch.setattr(
        "superharness.commands.doctor.platform.system", lambda: "Darwin"
    )


def test_ai_driven_with_unavailable_automation_is_a_warning(
    project, linux, monkeypatch, capsys
):
    monkeypatch.setattr(
        notify, "_watcher_health", lambda *_a: (False, "Heartbeat missing")
    )

    line = _line(_doctor_lines(capsys, project), "automation:")

    assert line.startswith("WARN")
    assert "ai_driven configured" in line
    assert "Heartbeat missing" in line


def test_ai_driven_with_healthy_watcher_passes(project, linux, monkeypatch, capsys):
    monkeypatch.setattr(notify, "_watcher_health", lambda *_a: (True, "healthy"))

    line = _line(_doctor_lines(capsys, project), "automation:")

    assert line.startswith("PASS")


def test_owner_disabled_operator_is_reported_as_intentional(
    project, darwin, monkeypatch, capsys
):
    monkeypatch.setattr(
        notify, "_watcher_health", lambda *_a: (True, "disabled by user")
    )
    monkeypatch.setattr(launchd_health, "read_watchdog_last_run", lambda: None)

    line = _line(_doctor_lines(capsys, project), "automation:")

    assert line.startswith("INFO")
    assert "disabled by user" in line


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        (None, "WARN watchdog: no last-run receipt"),
        (
            {"finished_at": _iso(time.time() - 7200), "projects": 1, "failures": []},
            "WARN watchdog: last run",
        ),
        (
            {
                "finished_at": _iso(time.time() - 60),
                "projects": 2,
                "failures": [{"project": "/p", "error": "boom"}],
            },
            "WARN watchdog: 1 project(s) failed",
        ),
        (
            {"finished_at": _iso(time.time() - 60), "projects": 2, "failures": []},
            "PASS watchdog: last run",
        ),
    ],
)
def test_watchdog_receipt_is_checked_on_macos(
    project, darwin, monkeypatch, capsys, receipt, expected
):
    monkeypatch.setattr(notify, "_watcher_health", lambda *_a: (True, "healthy"))
    monkeypatch.setattr(launchd_health, "read_watchdog_last_run", lambda: receipt)

    line = _line(_doctor_lines(capsys, project), "watchdog:")

    assert line.startswith(expected)


def test_open_outage_and_last_alert_are_shown(project, linux, monkeypatch, capsys):
    monkeypatch.setattr(notify, "_watcher_health", lambda *_a: (False, "down"))
    sent = int(time.time()) - 120
    (project / ".superharness" / "notify.state").write_text(
        f"WATCHER_DOWN_STREAK=4\nLAST_SENT_EPOCH={sent}\n"
        "LAST_FINGERPRINT=watcher=1|retry=0:\nWATCHER_ALERT_ACTIVE=1\n"
    )

    line = _line(_doctor_lines(capsys, project), "alerts:")

    assert _iso(sent) in line
    assert "outage alert open" in line
