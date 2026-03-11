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
        script = repo_root / "scripts" / "inbox-watch.sh"
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
        script = repo_root / "scripts" / "inbox-watch.sh"
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
        script = repo_root / "scripts" / "inbox-watch.sh"
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

    script = repo_root / "scripts" / "inbox-watch.sh"
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


def test_watch_rejects_invalid_lock_stale_minutes(repo_root, tmp_path) -> None:
    project = _write_project(tmp_path)

    script = repo_root / "scripts" / "inbox-watch.sh"
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
