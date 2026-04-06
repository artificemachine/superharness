"""Tests for shux daemon command."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


def test_daemon_status_no_state(project):
    from click.testing import CliRunner
    from superharness.commands.daemon import cmd_daemon

    runner = CliRunner()
    result = runner.invoke(cmd_daemon, ["status", "--project", str(project)])
    assert result.exit_code == 0
    assert "not running" in result.output


def test_daemon_stop_no_state(project):
    from click.testing import CliRunner
    from superharness.commands.daemon import cmd_daemon

    runner = CliRunner()
    result = runner.invoke(cmd_daemon, ["stop", "--project", str(project)])
    assert result.exit_code == 0
    assert "no state" in result.output


def test_daemon_start_missing_superharness_dir(tmp_path):
    """daemon start should fail cleanly when .superharness/ doesn't exist."""
    from click.testing import CliRunner
    from superharness.commands.daemon import cmd_daemon

    empty = tmp_path / "empty"
    empty.mkdir()
    runner = CliRunner()
    result = runner.invoke(cmd_daemon, ["start", "--project", str(empty)])
    assert result.exit_code != 0
    assert "no .superharness" in result.output.lower() or "no .superharness" in (result.output + "").lower()


def test_daemon_status_stale_pid(project):
    """Status should report stopped when PID no longer exists."""
    from click.testing import CliRunner
    from superharness.commands.daemon import cmd_daemon, _write_state

    _write_state(project, {"pid": 999999999, "project": str(project), "interval": 30})
    runner = CliRunner()
    result = runner.invoke(cmd_daemon, ["status", "--project", str(project)])
    assert result.exit_code == 0
    assert "stale" in result.output or "stopped" in result.output
