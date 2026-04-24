"""Tests for superharness.commands.inbox_watch (Python module).

Tests via subprocess: python3 -m superharness.commands.inbox_watch
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from superharness.engine.platform_runtime import watcher_lock_path


PYTHON = sys.executable

INBOX_HEADER = (
    "# Delegation inbox\n"
    "# status: pending|launched|running|done|failed|stale\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: t1\n    owner: codex-cli\n    status: plan_approved\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    (harness / "inbox.yaml").write_text(INBOX_HEADER)
    return project


def _lock_dir(project: Path) -> Path:
    return Path(watcher_lock_path(str(project)))


def _run_watch(project: Path, args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"
    # Skip PTY wrapping — CI runners have no TTY and `script` sometimes
    # fails opaquely, turning the launched item into "status: failed".
    env["SUPERHARNESS_NO_PTY_WRAP"] = "1"
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.inbox_watch",
         "--project", str(project)] + (args or []),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_watch_single_cycle_exits_zero(tmp_path: Path) -> None:
    """--once flag runs one cycle and exits."""
    project = _make_project(tmp_path)
    r = _run_watch(project, ["--once", "--print-only"])
    assert r.returncode == 0, r.stderr


def test_watch_lock_prevents_concurrent(tmp_path: Path) -> None:
    """Concurrent watcher is rejected (returns 0 with 'already running')."""
    project = _make_project(tmp_path)
    lock_dir = _lock_dir(project)
    lock_dir.mkdir(exist_ok=True)

    try:
        r = _run_watch(project, ["--once", "--print-only"])
        assert r.returncode == 0
        assert "Watcher already running" in r.stdout
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()


def test_watch_stale_lock_auto_broken(tmp_path: Path) -> None:
    """Lock older than threshold is auto-broken."""
    project = _make_project(tmp_path)
    lock_dir = _lock_dir(project)
    lock_dir.mkdir(exist_ok=True)
    stale_time = time.time() - (35 * 60)
    os.utime(str(lock_dir), (stale_time, stale_time))

    try:
        r = _run_watch(project, ["--once", "--print-only", "--lock-stale-minutes", "30"])
        assert r.returncode == 0, r.stderr
        assert "Auto-breaking stale watcher lock" in r.stdout
    finally:
        if lock_dir.exists():
            try:
                lock_dir.rmdir()
            except OSError:
                pass


def test_acquire_lock_writes_owner_pid(tmp_path: Path) -> None:
    """_acquire_watcher_lock writes owner.pid with the current process PID."""
    project = _make_project(tmp_path)
    lock_dir = _lock_dir(project)
    assert not lock_dir.exists()

    from superharness.commands.inbox_watch import _acquire_watcher_lock
    assert _acquire_watcher_lock(str(lock_dir)) is True

    pid_file = lock_dir / "owner.pid"
    assert pid_file.exists(), "owner.pid was not created"
    recorded_pid = int(pid_file.read_text().strip())
    assert recorded_pid == os.getpid(), f"expected PID {os.getpid()}, got {recorded_pid}"

    # cleanup
    pid_file.unlink()
    lock_dir.rmdir()


def test_orphaned_lock_broken_by_dead_pid(tmp_path: Path) -> None:
    """Python watcher breaks lock when owner.pid references a dead process."""
    project = _make_project(tmp_path)
    lock_dir = _lock_dir(project)
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "owner.pid").write_text("999999\n")

    r = _run_watch(project, ["--once", "--print-only"])
    assert r.returncode == 0, r.stderr
    assert "Auto-breaking orphaned watcher lock" in r.stdout
    assert "pid 999999 not running" in r.stdout


def test_live_pid_lock_not_broken(tmp_path: Path) -> None:
    """Lock with a live PID (our own) is NOT broken."""
    project = _make_project(tmp_path)
    lock_dir = _lock_dir(project)
    lock_dir.mkdir(parents=True, exist_ok=True)
    (lock_dir / "owner.pid").write_text(f"{os.getpid()}\n")

    try:
        r = _run_watch(project, ["--once", "--print-only"])
        assert r.returncode == 0
        assert "Watcher already running" in r.stdout
        assert "Auto-breaking" not in r.stdout
    finally:
        if lock_dir.exists():
            for child in lock_dir.iterdir():
                child.unlink()
            lock_dir.rmdir()


def test_watch_calls_dispatch_for_pending_items(tmp_path: Path) -> None:
    """Cycle calls dispatch when inbox has pending items."""
    project = _make_project(tmp_path)
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text(
        INBOX_HEADER + "\n"
        "- id: pending-item\n"
        "  to: claude-code\n"
        "  task: t1\n"
        f"  project: {project}\n"
        "  status: pending\n"
        "  priority: 1\n"
        "  retry_count: 0\n"
        "  max_retries: 3\n"
        "  created_at: 2026-01-01T00:00:00Z\n"
    )
    r = _run_watch(project, ["--once", "--to", "claude-code", "--print-only"])
    assert r.returncode == 0, r.stderr
    text = inbox.read_text()
    assert "status: launched" in text
