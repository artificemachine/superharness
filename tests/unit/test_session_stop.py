"""Tests for session-stop.sh — automatic context persistence on session exit."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

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

    def test_monitor_not_killed_on_session_stop(self, repo_root: Path) -> None:
        """Monitor dashboard is persistent — session-stop.sh must NOT kill it.

        The monitor is a long-running dashboard accessed from the browser independently
        of any Claude session. Killing it on session stop would break the UX.
        """
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        src = script.read_text()
        assert "monitor-ui.py" not in src or "pkill" not in src, (
            "session-stop.sh must not kill the monitor dashboard — "
            "it is a persistent service, not a session artifact"
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


_INBOX_HEADER = "# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n"


class TestSessionStopPausesTasks:
    """session-stop.sh must pause active inbox items and revert in-progress contract tasks."""

    def _make_inbox(self, harness: Path, items: list[dict]) -> Path:
        inbox = harness / "inbox.json"
        inbox.write_text(
            _INBOX_HEADER + yaml.dump(items, default_flow_style=False, allow_unicode=True)
        )
        return inbox

    def test_pauses_pending_inbox_items(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        harness = project / ".superharness"
        inbox = self._make_inbox(harness, [
            {"id": "item-001", "to": "claude-code", "task": "t1", "status": "pending",
             "priority": 1, "retry_count": 0, "max_retries": 3, "created_at": "2026-01-01T00:00:00Z"},
        ])
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        loaded = yaml.safe_load(inbox.read_text())
        assert loaded[0]["status"] == "paused", f"Expected paused, got {loaded[0]['status']}"
        assert "paused_at" in loaded[0]

    def test_pauses_launched_inbox_items(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        harness = project / ".superharness"
        inbox = self._make_inbox(harness, [
            {"id": "item-002", "to": "codex-cli", "task": "t2", "status": "launched",
             "priority": 1, "retry_count": 0, "max_retries": 3, "created_at": "2026-01-01T00:00:00Z"},
        ])
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        loaded = yaml.safe_load(inbox.read_text())
        assert loaded[0]["status"] == "paused"

    def test_pauses_running_inbox_items(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        harness = project / ".superharness"
        inbox = self._make_inbox(harness, [
            {"id": "item-003", "to": "codex-cli", "task": "t3", "status": "running",
             "priority": 1, "retry_count": 0, "max_retries": 3, "created_at": "2026-01-01T00:00:00Z"},
        ])
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        loaded = yaml.safe_load(inbox.read_text())
        assert loaded[0]["status"] == "paused"

    def test_skips_done_and_stopped_items(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        harness = project / ".superharness"
        inbox = self._make_inbox(harness, [
            {"id": "item-done", "status": "done"},
            {"id": "item-stopped", "status": "stopped"},
        ])
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        loaded = yaml.safe_load(inbox.read_text())
        assert loaded[0]["status"] == "done"
        assert loaded[1]["status"] == "stopped"

    def test_no_inbox_file_no_crash(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr

    def test_in_progress_contract_tasks_set_to_todo(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path, task_status="in_progress")
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        result = run_bash(script, cwd=project)
        assert result.returncode == 0, result.stderr
        contract = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
        task = next(t for t in contract["tasks"] if t["id"] == "feat-001")
        assert task["status"] == "todo", f"Expected todo, got {task['status']}"

    def test_todo_contract_tasks_not_touched(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path, task_status="todo")
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        contract = yaml.safe_load((project / ".superharness" / "contract.yaml").read_text())
        task = next(t for t in contract["tasks"] if t["id"] == "feat-001")
        assert task["status"] == "todo"

    def test_ledger_records_paused_items(self, repo_root: Path, tmp_path: Path) -> None:
        project = _setup_project(tmp_path)
        harness = project / ".superharness"
        self._make_inbox(harness, [{"id": "item-xyz", "status": "pending"}])
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        run_bash(script, cwd=project)
        ledger = (harness / "ledger.md").read_text()
        assert "item-xyz" in ledger

    def test_monitor_not_killed_by_project_path(self, repo_root: Path) -> None:
        """Monitor dashboard must not be killed by project path either.

        The monitor is persistent across sessions — neither port-based nor
        path-based killing should appear in session-stop.sh.
        """
        script = repo_root / "adapters" / "claude-code" / "hooks" / "session-stop.sh"
        src = script.read_text()
        assert not ("pkill" in src and "monitor-ui.py" in src), (
            "session-stop.sh must not pkill monitor-ui.py — "
            "the monitor is a persistent service, not a session artifact"
        )
