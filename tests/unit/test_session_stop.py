"""Tests for session-stop.sh — automatic context persistence on session exit."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from tests.helpers import run_bash
import sys
import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

def _setup_project(tmp_path: Path, *, task_status: str = "in_progress") -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        f"id: demo\n"
        f"tasks:\n"
        f"  - id: feat-001\n"
        f"    title: Build feature one\n"
        f"    owner: claude-code\n"
        f"    status: {task_status}\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")
    return project


def _init_git(project: Path, *, branch: str = "feat/test-branch") -> None:
    subprocess.run(["git", "init", str(project)], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(project), "checkout", "-b", branch], capture_output=True, check=True)
    # Initial commit so git log works
    dummy = project / "README.md"
    dummy.write_text("# test\n")
    subprocess.run(["git", "-C", str(project), "add", "README.md"], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(project), "commit", "-m", "initial commit", "--no-gpg-sign"],
        capture_output=True, check=True,
        env={**__import__("os").environ, "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@test.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@test.com"},
    )


class TestSessionStop:
    def test_writes_progress_file(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        progress = project / ".superharness" / "session-progress.md"
        assert progress.exists(), "session-stop.sh must write session-progress.md"

    def test_includes_task_status(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        content = (project / ".superharness" / "session-progress.md").read_text()
        assert "feat-001" in content
        assert "in_progress" in content

    def test_includes_git_branch(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        _init_git(project, branch="feat/my-feature")
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        content = (project / ".superharness" / "session-progress.md").read_text()
        assert "feat/my-feature" in content

    def test_includes_uncommitted_changes(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        _init_git(project)
        # Create an uncommitted file
        (project / "new_file.py").write_text("print('hello')\n")
        subprocess.run(["git", "-C", str(project), "add", "new_file.py"], capture_output=True, check=True)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        content = (project / ".superharness" / "session-progress.md").read_text()
        assert "new_file.py" in content

    def test_no_superharness_dir_noop(self, repo_root: Path, tmp_path: Path) -> None:
        project = tmp_path / "empty"
        project.mkdir()
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0
        assert not (project / ".superharness" / "session-progress.md").exists()

    def test_appends_ledger_entry(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        ledger = (project / ".superharness" / "ledger.md").read_text()
        assert "session-stop" in ledger
        assert "session-progress.md" in ledger

    def test_overwrites_previous_progress(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        run_bash(script, cwd=project)
        content = (project / ".superharness" / "session-progress.md").read_text()
        # Only one "Last updated" header — file was overwritten, not appended
        assert content.count("Last updated:") == 1

    def test_monitor_kill_respects_env_var_port(self, repo_root: Path, tmp_path: Path) -> None:
        """SUPERHARNESS_MONITOR_PORT env var is used instead of hardcoded 8787."""
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        # Use a port extremely unlikely to be in use; script must not crash
        result = run_bash(script, cwd=project, env={"SUPERHARNESS_MONITOR_PORT": "19876"})
        assert result.returncode == 0, result.stderr

    def test_no_listener_on_port_is_noop(self, repo_root: Path, tmp_path: Path) -> None:
        """When lsof finds no listener on the monitor port, session-stop does nothing."""
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"

        # Start a background sleep process (unrelated, no superharness cmdline)
        proc = subprocess.Popen(["sleep", "60"])
        try:
            result = run_bash(
                script, cwd=project,
                env={"SUPERHARNESS_MONITOR_PORT": "19877"},
            )
            assert result.returncode == 0, result.stderr
            assert proc.poll() is None, "session-stop.sh must not kill unrelated processes"
        finally:
            proc.terminate()
            proc.wait()

    def test_monitor_kill_guard_checks_process_name(self, repo_root: Path) -> None:
        """Regression: session-stop.sh must verify process name before killing.

        The guard 'grep -q superharness' prevents killing unrelated services that
        happen to use the same port. This test pins the pattern so it can't be
        silently removed.
        """
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        src = script.read_text()
        assert 'grep -q "superharness"' in src, (
            "session-stop.sh must check process cmdline for 'superharness' before "
            "killing the monitor process — removing this guard would allow killing "
            "unrelated services on the same port"
        )


class TestSessionStartReadsProgress:
    def test_session_start_includes_progress_snapshot(self, repo_root: Path, tmp_path: Path) -> None:
        """session-start.sh must include session-progress.md content in additionalContext."""
        project = tmp_path / "proj"
        project.mkdir()
        harness = project / ".superharness"
        (harness / "handoffs").mkdir(parents=True)
        (harness / "contract.yaml").write_text("id: x\n")

        # Write a fake progress file
        (harness / "session-progress.md").write_text(
            "# Session Progress\n"
            "## Task Context\n"
            "Active task: feat-001 (in_progress)\n"
            "## Branch\nfeat/my-branch\n"
        )

        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-start.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        context = payload["additionalContext"]
        assert "Previous Session Snapshot" in context
        assert "feat-001" in context
        assert "feat/my-branch" in context

    def test_session_start_works_without_progress_file(self, repo_root: Path, tmp_path: Path) -> None:
        """session-start.sh must work fine when no session-progress.md exists."""
        project = tmp_path / "proj"
        project.mkdir()
        harness = project / ".superharness"
        (harness / "handoffs").mkdir(parents=True)
        (harness / "contract.yaml").write_text("id: x\n")

        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-start.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        # No crash, valid JSON, no "Previous Session" section
        assert "additionalContext" in payload
