"""Tests for superharness.commands.inbox_watch (Python module).

Tests via subprocess: python3 -m superharness.commands.inbox_watch
"""
from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

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
        "  - id: t1\n    owner: codex-cli\n    status: todo\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    (harness / "inbox.yaml").write_text(INBOX_HEADER)
    return project


def _lock_key(project_dir: str) -> str:
    return hashlib.sha1(project_dir.encode()).hexdigest()


def _run_watch(project: Path, args: list[str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"
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
    lock_key = _lock_key(str(project))
    lock_dir = Path(f"/tmp/superharness-inbox-watch-{lock_key}.lock")
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
    lock_key = _lock_key(str(project))
    lock_dir = Path(f"/tmp/superharness-inbox-watch-{lock_key}.lock")
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
