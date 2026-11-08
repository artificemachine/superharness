"""The launchd watchdog evaluates owner alerts for every discovered project.

- The watchdog plist runs `operator heal --auto-discover --quiet --notify`.
- Alert outcomes (sent, suppressed, delivery failed) never change the
  watchdog exit code: the plist uses failure-only KeepAlive, so a non-zero
  exit would make launchd relaunch it immediately.
- One project's evaluation error does not stop the others and is recorded.
- Every run writes a last-run receipt so a dead watchdog is detectable.
- Without --notify, heal behaves as before and evaluates nothing.
"""

from __future__ import annotations

import json
import plistlib

import pytest
from click.testing import CliRunner

from superharness.cli import main as cli
from superharness.commands import notify
from superharness.engine import launchd_health


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    path = tmp_path / "state"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(path))
    return path


@pytest.fixture
def two_projects(tmp_path, monkeypatch):
    projects = [tmp_path / "a", tmp_path / "b"]

    def fake_heal_all(search_roots=None):
        reports = []
        for project in projects:
            report = launchd_health.HealReport([], [], [], [])
            report.label = launchd_health.operator_label_for_project(project)
            report.project = str(project)
            reports.append(report)
        return reports

    monkeypatch.setattr(launchd_health, "heal_all", fake_heal_all)
    return projects


def _heal(*extra):
    return CliRunner().invoke(
        cli, ["operator", "heal", "--auto-discover", "--quiet", *extra]
    )


def test_watchdog_plist_requests_notifications(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    (fake_home / "Library" / "LaunchAgents").mkdir(parents=True)
    monkeypatch.setattr(
        "superharness.engine.launchd_health.Path.home",
        classmethod(lambda cls: fake_home),
    )
    monkeypatch.setattr(launchd_health.platform, "system", lambda: "Darwin")

    plist = launchd_health.write_watchdog_plist(python_bin="/usr/bin/python3")
    arguments = plistlib.loads(plist.read_bytes())["ProgramArguments"]

    assert arguments[-4:] == ["heal", "--auto-discover", "--quiet", "--notify"]


@pytest.mark.parametrize("code", [0, 10, 11, 12])
def test_alert_outcome_never_changes_watchdog_exit_code(
    two_projects, state_dir, monkeypatch, code
):
    evaluated = []
    monkeypatch.setattr(
        notify,
        "evaluate_alerts",
        lambda project_dir, **_kw: evaluated.append(project_dir) or code,
    )

    result = _heal("--notify")

    assert result.exit_code == 0, result.output
    assert evaluated == [str(p) for p in two_projects]


def test_one_project_error_does_not_stop_the_others(
    two_projects, state_dir, monkeypatch
):
    evaluated = []

    def flaky(project_dir, **_kw):
        evaluated.append(project_dir)
        if project_dir == str(two_projects[0]):
            raise RuntimeError("state file unreadable")
        return 0

    monkeypatch.setattr(notify, "evaluate_alerts", flaky)

    result = _heal("--notify")

    assert result.exit_code == 0, result.output
    assert evaluated == [str(p) for p in two_projects]
    receipt = json.loads((state_dir / "watchdog-last-run.json").read_text())
    assert receipt["projects"] == 2
    assert receipt["failures"] == [
        {"project": str(two_projects[0]), "error": "state file unreadable"}
    ]


def test_every_notify_run_writes_a_last_run_receipt(
    two_projects, state_dir, monkeypatch
):
    monkeypatch.setattr(notify, "evaluate_alerts", lambda *_a, **_kw: 0)

    _heal("--notify")

    receipt = json.loads((state_dir / "watchdog-last-run.json").read_text())
    assert receipt["projects"] == 2
    assert receipt["failures"] == []
    assert receipt["finished_at"].endswith("Z")
    assert launchd_health.read_watchdog_last_run() == receipt


def test_quiet_run_hides_routine_outcomes_but_shows_alerts(
    two_projects, state_dir, monkeypatch
):
    def evaluate(project_dir, **_kw):
        if project_dir == str(two_projects[0]):
            print("notify: no alerts (watcher_ok=1 retry_high=0)")
            return 0
        print("superharness alert for b: watcher_down:3 (down)")
        return 10

    monkeypatch.setattr(notify, "evaluate_alerts", evaluate)

    result = _heal("--notify")

    assert "no alerts" not in result.output
    assert "watcher_down:3" in result.output


def test_heal_without_notify_evaluates_nothing(two_projects, state_dir, monkeypatch):
    def must_not_run(*_a, **_kw):
        raise AssertionError("evaluate_alerts called without --notify")

    monkeypatch.setattr(notify, "evaluate_alerts", must_not_run)

    result = _heal()

    assert result.exit_code == 0, result.output
    assert not (state_dir / "watchdog-last-run.json").exists()


def test_evaluate_alerts_returns_codes_instead_of_exiting(tmp_path, monkeypatch):
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notify, "_retry_high_ids", lambda *_a: [])
    monkeypatch.setattr(notify, "_watcher_health", lambda *_a: (True, "healthy"))

    assert notify.evaluate_alerts(str(project)) == 0
