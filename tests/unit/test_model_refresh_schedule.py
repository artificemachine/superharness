"""Tests for `shux models schedule` (engine/model_refresh_schedule.py)."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from superharness.commands.models import main as models_main
from superharness.engine import model_refresh_schedule as schedule

LABEL = "com.superharness.models-refresh"


class _FakeRunner:
    """Records every command; answers launchctl print with `loaded` and the rest with `rc`."""

    def __init__(self, rc: int = 0, stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.rc = rc
        self.stderr = stderr
        self.loaded = False

    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(cmd)
        if cmd[:2] == ["launchctl", "print"]:
            return subprocess.CompletedProcess(cmd, 0 if self.loaded else 113, "", "")
        if self.rc == 0 and cmd[:2] == ["launchctl", "bootstrap"]:
            self.loaded = True
        if self.rc == 0 and cmd[:2] == ["launchctl", "bootout"]:
            self.loaded = False
        return subprocess.CompletedProcess(cmd, self.rc, "", self.stderr)


@pytest.fixture
def installed_shux(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `shux` outside any git checkout, found on PATH."""
    shux = tmp_path / "pipx" / "bin" / "shux"
    shux.parent.mkdir(parents=True)
    shux.write_text("#!/bin/sh\n")
    shux.chmod(0o755)
    monkeypatch.setattr(schedule, "_which", lambda name: str(shux))
    return shux


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> _FakeRunner:
    fake = _FakeRunner()
    monkeypatch.setattr(schedule, "_run", fake)
    monkeypatch.setattr(schedule, "_platform", lambda: "darwin")
    return fake


def test_launchd_plist_runs_installed_shux_daily(tmp_path: Path) -> None:
    """The plist names the label, the absolute shux, `models refresh`, a daily time and the logs."""
    shux = Path("/opt/pipx/bin/shux")
    log_dir = tmp_path / "Library" / "Logs" / "superharness"

    plist = plistlib.loads(schedule.launchd_plist(shux, hour=9, minute=17, log_dir=log_dir).encode())

    assert plist["Label"] == LABEL
    assert plist["ProgramArguments"] == [str(shux), "models", "refresh"]
    assert plist["StartCalendarInterval"] == {"Hour": 9, "Minute": 17}
    assert plist["StandardOutPath"] == str(log_dir / f"{LABEL}.out.log")
    assert plist["StandardErrorPath"] == str(log_dir / f"{LABEL}.err.log")
    assert "KeepAlive" not in plist
    assert plist["EnvironmentVariables"]["PATH"].split(":")[0] == str(shux.parent)


def test_install_without_apply_writes_nothing(
    tmp_path: Path, installed_shux: Path, runner: _FakeRunner
) -> None:
    """A dry run prints the plist and the launchctl command; no file, no launchctl call."""
    home = tmp_path / "home"
    home.mkdir()

    result = CliRunner().invoke(models_main, ["schedule", "install", "--home", str(home)])

    assert result.exit_code == 0, result.output
    assert f"<string>{installed_shux}</string>" in result.output
    assert "launchctl bootstrap" in result.output
    assert "dry run" in result.output
    assert list(home.rglob("*")) == []
    assert runner.calls == []


def test_install_refuses_a_checkout_shux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: _FakeRunner
) -> None:
    """A shux inside a git checkout (for example its .venv) is refused with exit 1."""
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    shux = checkout / ".venv" / "bin" / "shux"
    shux.parent.mkdir(parents=True)
    shux.write_text("#!/bin/sh\n")
    monkeypatch.setattr(schedule, "_which", lambda name: str(shux))
    home = tmp_path / "home"
    home.mkdir()

    for args in (["install"], ["install", "--apply"]):
        result = CliRunner().invoke(models_main, ["schedule", *args, "--home", str(home)])
        assert result.exit_code == 1
        assert "checkout" in result.output
    assert list(home.rglob("*")) == []
    assert runner.calls == []


def test_install_apply_then_uninstall_apply_leaves_nothing(
    tmp_path: Path, installed_shux: Path, runner: _FakeRunner
) -> None:
    """Install writes and bootstraps the plist; uninstall boots it out and deletes it."""
    home = tmp_path / "home"
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "other.plist").write_text("keep")
    before = sorted(p.name for p in agents.iterdir())
    plist_path = agents / f"{LABEL}.plist"

    installed = CliRunner().invoke(models_main, ["schedule", "install", "--home", str(home), "--apply"])

    assert installed.exit_code == 0, installed.output
    assert plist_path.exists()
    assert ["launchctl", "bootstrap", f"gui/{schedule._uid()}", str(plist_path)] in runner.calls
    status = CliRunner().invoke(models_main, ["schedule", "status", "--home", str(home)])
    assert "scheduler: installed and loaded" in status.output

    removed = CliRunner().invoke(models_main, ["schedule", "uninstall", "--home", str(home), "--apply"])

    assert removed.exit_code == 0, removed.output
    assert ["launchctl", "bootout", f"gui/{schedule._uid()}/{LABEL}"] in runner.calls
    assert sorted(p.name for p in agents.iterdir()) == before

    # A launchctl failure surfaces its stderr, exits 1 and leaves no plist behind.
    runner.rc, runner.stderr = 5, "Bootstrap failed: 5: Input/output error"
    failed = CliRunner().invoke(models_main, ["schedule", "install", "--home", str(home), "--apply"])
    assert failed.exit_code == 1
    assert "Bootstrap failed: 5: Input/output error" in failed.output
    assert sorted(p.name for p in agents.iterdir()) == before
