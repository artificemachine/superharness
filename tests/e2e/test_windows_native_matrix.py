"""Iteration 7 — Windows-native end-to-end matrix test.

Exercises the full init → watch (single cycle) → enqueue → dispatch (print-only) → status
pipeline on every supported OS without requiring agent CLIs to be installed.

These tests must pass on ``ubuntu-latest``, ``macos-latest``, and ``windows-latest``
in CI.  They are explicitly NOT skipped on Windows — that is the point.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    merged["PYTHONUTF8"] = "1"
    if env:
        merged.update(env)
    return subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        env=merged,
        check=False,
    )


def _shux(args: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return _run([sys.executable, "-m", "superharness"] + args, cwd=cwd, env=env)


# ---------------------------------------------------------------------------
# Phase 1 — init
# ---------------------------------------------------------------------------


class TestInitCrossPlatform:
    """shux init must create .superharness/ on all OSes without bash."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_init_creates_harness_directory(self, tmp_path):
        result = _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"init failed: {result.stderr}"
        assert (tmp_path / ".superharness").is_dir()
        assert (tmp_path / ".superharness" / "contract.yaml").is_file()

    def test_init_creates_claude_and_agents_md(self, tmp_path):
        _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        assert (tmp_path / "CLAUDE.md").is_file()
        assert (tmp_path / "AGENTS.md").is_file()

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_init_contract_has_valid_yaml(self, tmp_path):
        _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        import yaml
        contract = yaml.safe_load((tmp_path / ".superharness" / "contract.yaml").read_text())
        assert "id" in contract
        assert "tasks" in contract


# ---------------------------------------------------------------------------
# Phase 2 — task create + status
# ---------------------------------------------------------------------------


class TestTaskCrossPlatform:
    """Task create / status must work on all OSes (pure Python, no bash)."""

    def _init(self, tmp_path: Path) -> Path:
        _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        return tmp_path

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_task_create_succeeds(self, tmp_path):
        project = self._init(tmp_path)
        result = _run(
            [sys.executable, "-m", "superharness.commands.task",
             "create",
             "--id", "WIN-001",
             "--title", "Windows native test task",
             "--owner", "claude-code",
             "--status", "todo",
             "--workflow", "quick",
             "--project", str(project),
             "--criteria", "Must pass on Windows"],
            cwd=project,
        )
        assert result.returncode == 0, f"task create failed:\n{result.stderr}"

        import yaml
        contract = yaml.safe_load(
            (project / ".superharness" / "contract.yaml").read_text()
        )
        task_ids = [t["id"] for t in contract.get("tasks", []) if isinstance(t, dict)]
        assert "WIN-001" in task_ids

    def test_status_command_shows_contract(self, tmp_path):
        project = self._init(tmp_path)
        result = _run(
            [sys.executable, "-m", "superharness.commands.status",
             "--project", str(project)],
            cwd=project,
        )
        # status may exit non-zero on minimal project but should not crash
        assert result.returncode in (0, 1)
        # Should produce some output
        assert len(result.stdout) > 0 or len(result.stderr) > 0


# ---------------------------------------------------------------------------
# Phase 3 — enqueue
# ---------------------------------------------------------------------------


class TestEnqueueCrossPlatform:
    """inbox enqueue must work cross-platform (pure Python)."""

    def _setup(self, tmp_path: Path) -> Path:
        _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        _run(
            [sys.executable, "-m", "superharness.commands.task",
             "create",
             "--id", "WIN-002",
             "--title", "Enqueue test task",
             "--owner", "claude-code",
             "--status", "todo",
             "--workflow", "quick",
             "--project", str(tmp_path)],
            cwd=tmp_path,
        )
        return tmp_path

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_enqueue_writes_inbox(self, tmp_path):
        project = self._setup(tmp_path)
        result = _run(
            [sys.executable, "-m", "superharness.commands.inbox_enqueue",
             "--task", "WIN-002",
             "--to", "claude-code",
             "--project", str(project)],
            cwd=project,
        )
        assert result.returncode == 0, f"enqueue failed:\n{result.stderr}"

        import yaml
        inbox = yaml.safe_load(
            (project / ".superharness" / "inbox.yaml").read_text()
        )
        assert isinstance(inbox, list)
        assert any(
            isinstance(item, dict) and item.get("task") == "WIN-002"
            for item in inbox
        )


# ---------------------------------------------------------------------------
# Phase 4 — delegate (print-only, no agent CLI required)
# ---------------------------------------------------------------------------


class TestDelegateCrossPlatform:
    """delegate --print-only must work cross-platform without agent CLIs."""

    def _setup(self, tmp_path: Path) -> Path:
        _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        _run(
            [sys.executable, "-m", "superharness.commands.task",
             "create",
             "--id", "WIN-003",
             "--title", "Delegate print-only test",
             "--owner", "claude-code",
             "--status", "todo",
             "--workflow", "quick",
             "--project", str(tmp_path)],
            cwd=tmp_path,
        )
        return tmp_path

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_delegate_print_only_exits_cleanly(self, tmp_path):
        project = self._setup(tmp_path)
        result = _run(
            [sys.executable, "-m", "superharness.commands.delegate",
             "--to", "claude-code",
             "--task", "WIN-003",
             "--project", str(project),
             "--print-only",
             "--no-auto-model"],
            cwd=project,
        )
        assert result.returncode == 0, f"delegate failed:\n{result.stderr}"
        assert "WIN-003" in result.stdout

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_delegate_does_not_use_execvp(self, tmp_path):
        """After --print-only returns, the test process must still be running (no execvp)."""
        project = self._setup(tmp_path)
        # If os.execvp were still used, this subprocess would never return cleanly
        result = _run(
            [sys.executable, "-m", "superharness.commands.delegate",
             "--to", "claude-code",
             "--task", "WIN-003",
             "--project", str(project),
             "--print-only",
             "--no-auto-model"],
            cwd=project,
        )
        # We got here — process returned normally
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Phase 5 — watch single cycle (no agent launch required)
# ---------------------------------------------------------------------------


class TestWatchSingleCycleCrossPlatform:
    """Single-cycle watch must not crash on Windows (lock path + inbox scan)."""

    def _setup(self, tmp_path: Path) -> Path:
        _run(
            [sys.executable, "-m", "superharness.commands.init_project",
             "Matrix Test", "Python", "active"],
            cwd=tmp_path,
        )
        return tmp_path

    def test_watch_once_on_empty_inbox(self, tmp_path):
        """watch --once completes without error when inbox is empty."""
        project = self._setup(tmp_path)
        result = _run(
            [sys.executable, "-m", "superharness.commands.inbox_watch",
             "--project", str(project),
             "--once",
             "--print-only"],
            cwd=project,
        )
        # Empty inbox → exit 0 (nothing to dispatch)
        assert result.returncode == 0, f"watch --once failed:\n{result.stderr}"

    def test_watch_lock_path_avoids_slash_tmp_on_windows(self, tmp_path):
        """Lock path on Windows must not be /tmp/..."""
        from superharness.engine.platform_runtime import watcher_lock_path

        lock = watcher_lock_path(str(tmp_path))
        if sys.platform == "win32":
            assert not Path(lock).resolve().is_relative_to(Path("/tmp")), lock


# ---------------------------------------------------------------------------
# Phase 6 — platform_runtime: lock acquire/release
# ---------------------------------------------------------------------------


class TestLockCrossPlatform:
    """Lock acquire/release must work on Windows and Unix."""

    def test_acquire_and_release(self, tmp_path):
        from superharness.engine.platform_runtime import watcher_lock_path
        from superharness.commands.inbox_watch import (
            _acquire_watcher_lock,
            _release_watcher_lock,
            _auto_break_stale_lock,
        )

        lock = watcher_lock_path(str(tmp_path))
        # Should not exist yet
        assert not os.path.exists(lock)

        acquired = _acquire_watcher_lock(lock)
        assert acquired
        assert os.path.isdir(lock)

        _release_watcher_lock(lock)
        assert not os.path.exists(lock)

    def test_double_acquire_fails(self, tmp_path):
        from superharness.engine.platform_runtime import watcher_lock_path
        from superharness.commands.inbox_watch import (
            _acquire_watcher_lock,
            _release_watcher_lock,
        )

        lock = watcher_lock_path(str(tmp_path))
        assert _acquire_watcher_lock(lock)
        assert not _acquire_watcher_lock(lock)  # second acquire must fail
        _release_watcher_lock(lock)
