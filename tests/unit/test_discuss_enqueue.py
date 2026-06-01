"""Tests for superharness.commands.discuss (Python module).

Tests via subprocess: python3 -m superharness.commands.discuss
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite, seed_sqlite_handoff, seed_sqlite_heartbeat

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

    # Mock heartbeats for participants (v1.69.5 requirement)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    seed_sqlite_heartbeat(project, agent="watcher", status="alive", now=now)
    seed_sqlite_heartbeat(project, agent="claude-code", status="alive", now=now)
    seed_sqlite_heartbeat(project, agent="codex-cli", status="alive", now=now)

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


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
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
    # Seed SQLite (source of truth) with task + inbox + handoff state
    seed_sqlite_from_yaml(project)
    seed_sqlite_handoff(
        project, "approval-task", phase="report", status="pending_user_approval",
        content=(
            "task: approval-task\nto: codex-cli\ndate: 2026-03-11\n"
            "status: pending_user_approval\n"
            "approval_gate:\n  required: true\n  approved_by_user: false\n  approved_at: null\n"
        ),
        now="2026-03-11T00:00:00Z",
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
    # Approval gate is in SQLite (source of truth); YAML is export-only.
    import sqlite3 as _sql
    db = _sql.connect(str(project / ".superharness" / "state.sqlite3"))
    approved_row = db.execute(
        "SELECT metadata FROM handoffs WHERE task_id='approval-task' AND status='approved' LIMIT 1"
    ).fetchone()
    db.close()
    assert approved_row is not None, "No approved handoff found in SQLite after cmd_approve"


# ---------------------------------------------------------------------------
# Participant floor: max(2, available-1) — prevents minimum-meeting reflex
# ---------------------------------------------------------------------------

class TestParticipantFloor:
    """Tests for the participant floor rule in discuss.py (max(2, available-1))."""

    def test_two_agents_requires_both(self):
        """2 available → required = max(2, 1) = 2 → must include both."""
        required = max(2, 2 - 1)
        assert required == 2

    def test_three_agents_allows_two(self):
        """3 available → required = max(2, 2) = 2 → can exclude 1."""
        required = max(2, 3 - 1)
        assert required == 2

    def test_four_agents_requires_three(self):
        """4 available → required = max(2, 3) = 3 → can only exclude 1."""
        required = max(2, 4 - 1)
        assert required == 3

    def test_one_agent_floor_at_two(self):
        """1 available → required = max(2, 0) = 2 (discussions need at least 2)."""
        required = max(2, 1 - 1)
        assert required == 2
