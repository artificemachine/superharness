"""Tests for superharness.commands.inbox_dispatch (Python module).

Tests via subprocess: python3 -m superharness.commands.inbox_dispatch
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import pytest

PYTHON = sys.executable

INBOX_HEADER = (
    "# Delegation inbox\n"
    "# status: pending|launched|running|done|failed|stale\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, *, inbox_items: list[dict] | None = None) -> Path:
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)

    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: test-task\n    owner: codex-cli\n    status: plan_approved\n"
        f"    project_path: '{project.as_posix()}'\n"
    )

    if inbox_items is not None:
        lines = [INBOX_HEADER]
        for item in inbox_items:
            lines.append(f"- id: {item['id']}")
            lines.append(f"  to: {item.get('to', 'codex-cli')}")
            lines.append(f"  task: {item.get('task', 'test-task')}")
            lines.append(f"  project: {project}")
            lines.append(f"  status: {item.get('status', 'pending')}")
            lines.append(f"  priority: {item.get('priority', 2)}")
            lines.append(f"  retry_count: {item.get('retry_count', 0)}")
            lines.append(f"  max_retries: {item.get('max_retries', 3)}")
            lines.append("  created_at: 2026-01-01T00:00:00Z")
        (harness / "inbox.yaml").write_text("\n".join(lines) + "\n")
    else:
        # Empty inbox
        (harness / "inbox.yaml").write_text(INBOX_HEADER)
    seed_sqlite_from_yaml(project)

    return project


def _fake_launcher_script(tmp_path: Path, name: str, exit_code: int = 0, sleep: float = 0) -> Path:
    """Create a fake launcher script."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    lines = ["#!/bin/bash"]
    if sleep > 0:
        lines.append(f"sleep {sleep}")
    lines.append(f"exit {exit_code}")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(0o755)
    return bin_dir


def _run_dispatch(project: Path, args: list[str] | None = None, bin_dir: Path | None = None, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    # Always allow non-interactive in tests
    env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"
    # Skip PTY wrapping — CI runners have no TTY and `script` sometimes
    # fails opaquely, turning the launched item into "status: failed".
    env["SUPERHARNESS_NO_PTY_WRAP"] = "1"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.inbox_dispatch",
         "--project", str(project)] + (args or []),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_dispatch_picks_next_pending(tmp_path: Path) -> None:
    project = _make_project(tmp_path, inbox_items=[
        {"id": "item-001", "to": "claude-code", "priority": 1},
    ])
    bin_dir = _fake_launcher_script(tmp_path, "claude")
    r = _run_dispatch(project, ["--to", "claude-code", "--print-only"], bin_dir)
    assert r.returncode == 0, r.stderr
    assert "item-001 -> launched" in r.stdout
    text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: launched" in text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_dispatch_no_pending_exits_zero(tmp_path: Path) -> None:
    project = _make_project(tmp_path)  # empty inbox
    r = _run_dispatch(project)
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_dispatch_lock_prevents_concurrent(tmp_path: Path) -> None:
    project = _make_project(tmp_path, inbox_items=[
        {"id": "lock-item", "to": "codex-cli"},
    ])
    inbox_file = project / ".superharness" / "inbox.yaml"
    lock_dir = project / ".superharness" / "inbox.yaml.lock.d"
    lock_dir.mkdir()

    try:
        r = _run_dispatch(project, ["--to", "codex-cli"])
        assert r.returncode == 0
        assert "Another inbox dispatcher" in r.stdout
    finally:
        if lock_dir.exists():
            lock_dir.rmdir()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_dispatch_retry_limit_marks_failed(tmp_path: Path) -> None:
    project = _make_project(tmp_path, inbox_items=[
        {"id": "exhaust-item", "to": "codex-cli", "retry_count": 3, "max_retries": 3},
    ])
    r = _run_dispatch(project, ["--to", "codex-cli"])
    assert r.returncode == 1
    assert "retry limit reached" in r.stdout
    text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: failed" in text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_dispatch_state_reconcile_done(tmp_path: Path) -> None:
    """When launcher exits 0 and contract task is done, inbox item becomes done."""
    project = _make_project(tmp_path, inbox_items=[
        {"id": "reconcile-done", "to": "codex-cli", "task": "test-task"},
    ])
    # Set task to done before dispatch so reconcile sees it
    contract = project / ".superharness" / "contract.yaml"
    contract.write_text(
        "id: test-contract\ntasks:\n"
        "  - id: test-task\n    owner: codex-cli\n    status: done\n"
        f"    project_path: '{project.as_posix()}'\n"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "codex").write_text("#!/bin/bash\necho fake-codex\n")
    (bin_dir / "codex").chmod(0o755)
    (bin_dir / "claude").write_text("#!/bin/bash\necho fake-claude\n")
    (bin_dir / "claude").chmod(0o755)

    r = _run_dispatch(project, ["--to", "codex-cli", "--non-interactive"], bin_dir)
    assert r.returncode == 0, r.stderr
    text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: done" in text


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_dispatch_state_reconcile_failed(tmp_path: Path) -> None:
    """When launcher exits non-zero, inbox item becomes failed."""
    project = _make_project(tmp_path, inbox_items=[
        {"id": "reconcile-fail", "to": "codex-cli", "task": "test-task"},
    ])

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "codex").write_text("#!/bin/bash\nexit 1\n")
    (bin_dir / "codex").chmod(0o755)
    (bin_dir / "claude").write_text("#!/bin/bash\nexit 1\n")
    (bin_dir / "claude").chmod(0o755)

    r = _run_dispatch(project, ["--to", "codex-cli", "--non-interactive"], bin_dir)
    assert r.returncode == 1
    text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: failed" in text


def test_dispatch_dirty_worktree_uses_worktree(tmp_path: Path) -> None:
    """Dirty worktree + non-interactive -> dispatches in a temporary worktree."""
    project = _make_project(tmp_path, inbox_items=[
        {"id": "dirty-item", "to": "codex-cli", "task": "test-task"},
    ])

    # Initialize a git repo and make it dirty
    subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@test.com"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], cwd=project, check=True, capture_output=True)
    tracked = project / "tracked.txt"
    tracked.write_text("base\n")
    subprocess.run(["git", "add", "tracked.txt"], cwd=project, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, check=True, capture_output=True)
    tracked.write_text("dirty\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "codex").write_text("#!/bin/bash\necho fake-codex\n")
    (bin_dir / "codex").chmod(0o755)
    (bin_dir / "claude").write_text("#!/bin/bash\necho fake-claude\n")
    (bin_dir / "claude").chmod(0o755)

    r = _run_dispatch(project, ["--to", "codex-cli", "--non-interactive"], bin_dir)
    # Should dispatch in worktree, not pause
    assert "worktree" in r.stdout.lower() or r.returncode == 0
    # Main worktree should still be dirty
    assert tracked.read_text() == "dirty\n"
