"""Tests for superharness.commands.discuss (Python module).

Tests via subprocess: python3 -m superharness.commands.discuss
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

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
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: discuss-task\n    owner: claude-code\n    status: todo\n"
        f"    project_path: '{project.as_posix()}'\n"
        "  - id: discuss-task-b\n    owner: codex-cli\n    status: todo\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    (harness / "inbox.yaml").write_text(INBOX_HEADER)
    seed_sqlite_from_yaml(project)
    return project


def _run_discuss(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.discuss"] + args,
        capture_output=True,
        text=True,
        check=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_discuss_start_creates_discussion(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_discuss([
        "start",
        "--project", str(project),
        "--topic", "Test discussion",
        "--max-rounds", "2",
    ])
    assert r.returncode == 0, r.stderr
    assert "Discussion started:" in r.stdout
    assert "Topic: Test discussion" in r.stdout
    # Discussion directory should be created
    disc_dir = project / ".superharness" / "discussions"
    assert disc_dir.exists()
    subdirs = list(disc_dir.iterdir())
    assert len(subdirs) == 1


def test_discuss_start_enqueues_round1(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    r = _run_discuss([
        "start",
        "--project", str(project),
        "--topic", "Round 1 test",
        "--max-rounds", "3",
    ])
    assert r.returncode == 0, r.stderr
    assert "Enqueued round 1 for claude-code" in r.stdout
    assert "Enqueued round 1 for codex-cli" in r.stdout
    # Inbox should have 2 pending items (count "  status: pending" lines, indented)
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert inbox_text.count("  status: pending") == 2


def test_discuss_approve_approves_handoff(tmp_path: Path) -> None:
    project = _make_project(tmp_path)
    harness = project / ".superharness"
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: approval-task\n    owner: codex-cli\n    status: pending_user_approval\n"
        f"    project_path: '{project.as_posix()}'\n"
    )
    (harness / "inbox.yaml").write_text(
        INBOX_HEADER + "\n"
        "- id: approval-item\n"
        "  to: codex-cli\n"
        "  task: approval-task\n"
        f"  project: {project}\n"
        "  status: paused\n"
        "  pause_reason: awaiting_user_approval\n"
        "  priority: 1\n"
        "  retry_count: 0\n"
        "  max_retries: 3\n"
    )
    (harness / "handoffs" / "2026-test-approval.yaml").write_text(
        "task: approval-task\n"
        "to: codex-cli\n"
        "date: 2026-03-11\n"
        "status: pending_user_approval\n"
        "approval_gate:\n"
        "  required: true\n"
        "  approved_by_user: false\n"
        "  approved_at: null\n"
    )
    r = _run_discuss([
        "approve",
        "--project", str(project),
        "--task", "approval-task",
        "--by", "owner",
        "--note", "Approved in test",
    ])
    assert r.returncode == 0, r.stderr
    assert "Approved" in r.stdout or "approved" in r.stdout.lower()
    handoff_text = (harness / "handoffs" / "2026-test-approval.yaml").read_text()
    assert "approved_by_user: true" in handoff_text
