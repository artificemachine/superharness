"""notify's macOS watcher probe must check the operator service that is
actually installed, not the pre-1.50 ``com.superharness.inbox.<slug>``
label that ``launchd_health`` treats as obsolete.

All launchctl calls are mocked; the suite runs the same on macOS and Linux.
"""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest

from superharness.commands import notify
from superharness.engine import launchd_health


@pytest.fixture
def launch_agents(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    agents = fake_home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    monkeypatch.setattr(
        "superharness.engine.launchd_health.Path.home",
        classmethod(lambda cls: fake_home),
    )
    monkeypatch.setattr(launchd_health.platform, "system", lambda: "Darwin")
    return agents


@pytest.fixture
def project(tmp_path):
    project_dir = tmp_path / "proj"
    (project_dir / ".superharness").mkdir(parents=True)
    return project_dir


def _install_operator_plist(agents: Path, label: str, project_dir: Path) -> None:
    with (agents / f"{label}.plist").open("wb") as fh:
        plistlib.dump(
            {
                "Label": label,
                "ProgramArguments": [
                    "python",
                    "-m",
                    "superharness.cli",
                    "operator",
                    "start",
                    "--no-daemon",
                    "--project",
                    str(project_dir),
                ],
            },
            fh,
        )


def _launchctl_print(state: str, last_exit: str) -> str:
    return f"gui/501/x = {{\n\tstate = {state}\n\tlast exit code = {last_exit}\n}}\n"


class _FakeLaunchctl:
    """Records every launchctl print target; answers from a per-label table."""

    def __init__(self, services: dict[str, str]):
        self.services = services
        self.printed: list[str] = []

    def __call__(self, argv, **_kwargs):
        if argv[:2] == ["launchctl", "print"]:
            target = argv[2]
            self.printed.append(target)
            label = target.rsplit("/", 1)[-1]
            if label in self.services:
                return subprocess.CompletedProcess(argv, 0, self.services[label], "")
            return subprocess.CompletedProcess(argv, 113, "", "not found")
        raise AssertionError(f"unexpected command: {argv}")


@pytest.fixture
def not_disabled(monkeypatch):
    monkeypatch.setattr(launchd_health, "is_disabled", lambda label: False)


def test_probe_targets_canonical_operator_label(
    launch_agents, project, monkeypatch, not_disabled
):
    canonical = launchd_health.operator_label_for_project(project)
    fake = _FakeLaunchctl({canonical: _launchctl_print("running", "0")})
    monkeypatch.setattr(notify.subprocess, "run", fake)

    ok, _detail = notify._watcher_ok_darwin(str(project))

    assert ok is True
    assert any(t.endswith(f"/{canonical}") for t in fake.printed)


def test_probe_never_targets_legacy_inbox_label(
    launch_agents, project, monkeypatch, not_disabled
):
    fake = _FakeLaunchctl({})
    monkeypatch.setattr(notify.subprocess, "run", fake)

    notify._watcher_ok_darwin(str(project))

    assert fake.printed, "the probe must query launchd"
    assert not any("com.superharness.inbox." in t for t in fake.printed)


def test_probe_follows_installed_plist_with_non_canonical_label(
    launch_agents, project, monkeypatch, not_disabled
):
    # A service installed under an older hash still owns the project
    # through its --project argument (operator_labels_for_project).
    legacy_hash_label = "com.superharness.operator.0ldhash0"
    _install_operator_plist(launch_agents, legacy_hash_label, project)
    fake = _FakeLaunchctl({legacy_hash_label: _launchctl_print("running", "0")})
    monkeypatch.setattr(notify.subprocess, "run", fake)

    ok, _detail = notify._watcher_ok_darwin(str(project))

    assert ok is True


def test_probe_reports_unloaded_service_as_down(
    launch_agents, project, monkeypatch, not_disabled
):
    monkeypatch.setattr(notify.subprocess, "run", _FakeLaunchctl({}))

    ok, detail = notify._watcher_ok_darwin(str(project))

    assert ok is False
    assert "not loaded" in detail


def test_probe_reports_failed_exit_as_down(
    launch_agents, project, monkeypatch, not_disabled
):
    canonical = launchd_health.operator_label_for_project(project)
    fake = _FakeLaunchctl({canonical: _launchctl_print("not running", "1")})
    monkeypatch.setattr(notify.subprocess, "run", fake)

    ok, detail = notify._watcher_ok_darwin(str(project))

    assert ok is False
    assert "exit=1" in detail


def test_probe_treats_owner_disabled_service_as_not_an_outage(
    launch_agents, project, monkeypatch
):
    canonical = launchd_health.operator_label_for_project(project)
    monkeypatch.setattr(launchd_health, "is_disabled", lambda label: label == canonical)
    monkeypatch.setattr(notify.subprocess, "run", _FakeLaunchctl({}))

    ok, detail = notify._watcher_ok_darwin(str(project))

    assert ok is True
    assert "disabled" in detail
