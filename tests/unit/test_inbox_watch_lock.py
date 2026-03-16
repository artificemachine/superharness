from __future__ import annotations

import os
import time
from pathlib import Path

from tests.helpers import run_bash


def _write_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: t1\n    owner: codex-cli\n    status: todo\n"
        f'    project_path: "{project}"\n'
    )
    (harness / "inbox.yaml").write_text(
        "# Delegation inbox\n"
        "# status: pending|launched|running|done|failed|stale\n\n"
    )
    return project


def _lock_key(project_dir: str) -> str:
    import hashlib
    return hashlib.sha1(project_dir.encode()).hexdigest()


def test_watch_auto_breaks_stale_lock(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    lock_key = _lock_key(str(project))
    lock_dir = Path(f"/tmp/superharness-inbox-watch-{lock_key}.lock")

    # Create a stale lock directory and backdate it
    lock_dir.mkdir(exist_ok=True)
    # Set mtime to 35 minutes ago
    stale_time = time.time() - (35 * 60)
    os.utime(str(lock_dir), (stale_time, stale_time))

    try:
        script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
        result = run_bash(
            script,
            cwd=repo_root,
            args=[
                "--project", str(project),
                "--to", "claude-code",
                "--print-only",
                "--lock-stale-minutes", "30",
            ],
        )

        assert result.returncode == 0, result.stderr
        assert "Auto-breaking stale watcher lock" in result.stdout
    finally:
        # Clean up lock dir if still present
        if lock_dir.exists():
            lock_dir.rmdir()


def test_watch_respects_fresh_lock(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    lock_key = _lock_key(str(project))
    lock_dir = Path(f"/tmp/superharness-inbox-watch-{lock_key}.lock")

    # Create a fresh lock (just now)
    lock_dir.mkdir(exist_ok=True)

    try:
        script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
        result = run_bash(
            script,
            cwd=repo_root,
            args=[
                "--project", str(project),
                "--to", "claude-code",
                "--print-only",
                "--lock-stale-minutes", "30",
            ],
        )

        assert result.returncode == 0
        assert "Watcher already running" in result.stdout
        assert "Auto-breaking" not in result.stdout
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()


def test_watch_lock_stale_disabled_with_zero(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    lock_key = _lock_key(str(project))
    lock_dir = Path(f"/tmp/superharness-inbox-watch-{lock_key}.lock")

    # Create an old lock
    lock_dir.mkdir(exist_ok=True)
    stale_time = time.time() - (60 * 60)
    os.utime(str(lock_dir), (stale_time, stale_time))

    try:
        script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
        result = run_bash(
            script,
            cwd=repo_root,
            args=[
                "--project", str(project),
                "--to", "claude-code",
                "--print-only",
                "--lock-stale-minutes", "0",
            ],
        )

        assert result.returncode == 0
        # With stale-minutes=0, auto-break is disabled; the lock should block
        assert "Watcher already running" in result.stdout
        assert "Auto-breaking" not in result.stdout
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()


def test_watch_passes_launcher_timeout_to_dispatch(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "claude-code",
            "--print-only",
            "--launcher-timeout", "60",
        ],
    )

    # Should run successfully (no pending items, but it exercises the arg passing)
    assert result.returncode == 0, result.stderr


def test_watch_accepts_recover_options(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--to", "claude-code",
            "--print-only",
            "--recover-timeout-minutes", "7",
            "--recover-action", "retry",
        ],
    )

    assert result.returncode == 0, result.stderr


def test_watch_rejects_invalid_recover_action(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--recover-action", "invalid",
        ],
    )

    assert result.returncode == 2
    assert "--recover-action must be one of: stale, retry" in result.stderr


def test_watch_rejects_invalid_recover_timeout_minutes(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--recover-timeout-minutes", "oops",
        ],
    )

    assert result.returncode == 2
    assert "--recover-timeout-minutes must be a non-negative integer" in result.stderr


def test_watch_foreground_exits_on_sigterm(repo_root, tmp_path) -> None:
    """Foreground mode should start and respond to SIGTERM."""
    import signal

    project = _write_project(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"

    import subprocess as sp

    proc = sp.Popen(
        ["bash", str(script),
         "--project", str(project),
         "--foreground",
         "--interval", "60",
         "--print-only"],
        stdout=sp.PIPE, stderr=sp.PIPE, text=True,
        cwd=repo_root,
    )

    # Wait for watcher startup message
    import select
import sys
import pytest
    ready, _, _ = select.select([proc.stdout], [], [], 5)

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")
    assert ready, "Foreground watcher did not produce output within 5s"

    # Read the startup lines
    line = proc.stdout.readline()
    assert "foreground" in line.lower() or "watcher" in line.lower()

    # Send SIGTERM
    proc.send_signal(signal.SIGTERM)
    proc.wait(timeout=5)
    assert proc.returncode == 0


def test_watch_foreground_rejects_zero_interval(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--foreground",
            "--interval", "0",
        ],
    )
    assert result.returncode == 2
    assert "positive integer" in result.stderr


def test_watch_validates_project_dir(repo_root, tmp_path) -> None:
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(tmp_path / "nonexistent")],
    )
    assert result.returncode == 1
    assert "does not exist" in result.stderr


def test_watch_validates_superharness_dir(repo_root, tmp_path) -> None:
    project = tmp_path / "no-harness"
    project.mkdir()
    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=["--project", str(project)],
    )
    assert result.returncode == 1
    assert "Not a superharness project" in result.stderr


def test_watch_rejects_invalid_lock_stale_minutes(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)

    script = repo_root / "src" / "superharness" / "scripts" / "inbox-watch.sh"
    result = run_bash(
        script,
        cwd=repo_root,
        args=[
            "--project", str(project),
            "--lock-stale-minutes", "abc",
        ],
    )

    assert result.returncode == 2
    assert "non-negative integer" in result.stderr
