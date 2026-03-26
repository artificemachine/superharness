"""Unit tests for `shux update` — git repo vs pipx/pip install detection."""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from superharness.cli import _is_git_repo, main


# ── _is_git_repo helper ────────────────────────────────────────────────────


def test_is_git_repo_returns_true_for_real_repo(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True,
                   capture_output=True)
    assert _is_git_repo(str(tmp_path)) is True


def test_is_git_repo_returns_false_for_plain_dir(tmp_path):
    assert _is_git_repo(str(tmp_path)) is False


def test_is_git_repo_returns_false_for_nonexistent_path():
    assert _is_git_repo("/nonexistent/path/xyz123") is False


# ── cmd_update — git repo path ─────────────────────────────────────────────


def test_update_uses_git_pull_when_root_is_repo(tmp_path):
    """When _ROOT is a git repo, step 1 must be git pull."""
    runner = CliRunner()
    with patch("superharness.cli._is_git_repo", return_value=True), \
         patch("superharness.cli.subprocess.run") as mock_run, \
         patch("superharness.cli._run_module"):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(main, ["update"])
    assert result.exit_code == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert any("pull" in cmd for cmd in calls), f"git pull not called: {calls}"
    assert result.output and "git pull" in result.output.lower()


def test_update_exits_nonzero_when_git_pull_fails(tmp_path):
    runner = CliRunner()
    with patch("superharness.cli._is_git_repo", return_value=True), \
         patch("superharness.cli.subprocess.run") as mock_run, \
         patch("superharness.cli._run_module"):
        mock_run.return_value = MagicMock(returncode=1)
        result = runner.invoke(main, ["update"])
    assert result.exit_code != 0


# ── cmd_update — pipx install path ────────────────────────────────────────


def test_update_uses_pipx_when_root_is_not_repo():
    """When _ROOT is not a git repo, step 1 must try pipx upgrade."""
    runner = CliRunner()
    with patch("superharness.cli._is_git_repo", return_value=False), \
         patch("superharness.cli.subprocess.run") as mock_run, \
         patch("superharness.cli._run_module"):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(main, ["update"])
    assert result.exit_code == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert any(
        "pipx" in cmd and "upgrade" in cmd and "superharness" in cmd
        for cmd in calls
    ), f"pipx upgrade not called: {calls}"


def test_update_falls_back_to_pip_when_pipx_unavailable():
    """When pipx upgrade fails, fall back to pip install --upgrade."""
    runner = CliRunner()

    def side_effect(cmd, **kwargs):
        m = MagicMock()
        if "pipx" in cmd:
            m.returncode = 1   # pipx not available / failed
        else:
            m.returncode = 0
        return m

    with patch("superharness.cli._is_git_repo", return_value=False), \
         patch("superharness.cli.subprocess.run", side_effect=side_effect) as mock_run, \
         patch("superharness.cli._run_module"):
        result = runner.invoke(main, ["update"])

    assert result.exit_code == 0
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert any(
        "pip" in cmd and "install" in cmd and "--upgrade" in cmd
        for cmd in calls
    ), f"pip fallback not called: {calls}"


def test_update_exits_nonzero_when_pip_fallback_also_fails():
    runner = CliRunner()

    def side_effect(cmd, **kwargs):
        m = MagicMock()
        m.returncode = 1   # everything fails
        return m

    with patch("superharness.cli._is_git_repo", return_value=False), \
         patch("superharness.cli.subprocess.run", side_effect=side_effect), \
         patch("superharness.cli._run_module"):
        result = runner.invoke(main, ["update"])

    assert result.exit_code != 0


def test_update_prints_pipx_done_message_on_success():
    runner = CliRunner()
    with patch("superharness.cli._is_git_repo", return_value=False), \
         patch("superharness.cli.subprocess.run") as mock_run, \
         patch("superharness.cli._run_module"):
        mock_run.return_value = MagicMock(returncode=0)
        result = runner.invoke(main, ["update"])
    assert "pipx upgrade superharness" in result.output
