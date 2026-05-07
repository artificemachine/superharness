"""Tests for _auto_close_consensus_discussions and _reconcile_discussion_contract.

Verifies both functions read discussion state from SQLite, not stale YAML files.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import discussions_dao
from superharness.commands.inbox_watch import (
    _auto_close_consensus_discussions,
    _reconcile_discussion_contract,
    _CONSENSUS_GRACE_MINUTES,
)

def _raw_create_task(conn: sqlite3.Connection, task_id: str, status: str = "in_progress",
                     owner: str = "claude-code", now: str | None = None) -> None:
    """Insert a task directly (bypassing the complex upsert signature)."""
    ts = now or now_iso()
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at, acceptance_criteria, test_types, out_of_scope, definition_of_done) "
        "VALUES (?, ?, ?, ?, ?, '[]', '[]', '[]', '[]')",
        (task_id, task_id, owner, status, ts),
    )

def _raw_create_inbox(conn: sqlite3.Connection, inbox_id: str, task_id: str,
                       target_agent: str = "claude-code", now: str | None = None) -> None:
    """Insert an inbox item directly."""
    ts = now or now_iso()
    conn.execute(
        "INSERT INTO inbox (id, task_id, target_agent, status, created_at, project_path) "
        "VALUES (?, ?, ?, 'pending', ?, '')",
        (inbox_id, task_id, target_agent, ts),
    )


@pytest.fixture
def project_with_db(tmp_path: Path) -> Path:
    """Project directory with initialized SQLite DB."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    return project


def _make_old_ts(hours_ago: int) -> str:
    """Return ISO timestamp N hours in the past."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _create_yaml_decoys(project: Path, disc_id: str, yaml_status: str) -> None:
    """Create a YAML state.yaml with a different status than SQLite (drift simulation)."""
    disc_dir = project / ".superharness" / "discussions" / disc_id
    disc_dir.mkdir(parents=True, exist_ok=True)
    (disc_dir / "state.yaml").write_text(
        f"status: {yaml_status}\n"
        f"topic: decoy\n"
        f"created_at: '2025-01-01T00:00:00Z'\n"
    )


def _write_contract_yaml(project: Path, task_id: str, status: str = "in_progress") -> None:
    """Write a contract.yaml entry so state_reader.get_tasks() finds the task in test mode."""
    contract_path = project / ".superharness" / "contract.yaml"
    existing = ""
    if contract_path.exists():
        existing = contract_path.read_text()
    entry = (
        f"  - id: {task_id}\n"
        f"    owner: claude-code\n"
        f"    status: {status}\n"
        f"    title: {task_id}\n"
    )
    if existing:
        # Insert before last newline
        contract_path.write_text(existing.rstrip() + "\n" + entry + "\n")
    else:
        contract_path.write_text("tasks:\n" + entry + "\n")


# ---------------------------------------------------------------------------
# _auto_close_consensus_discussions
# ---------------------------------------------------------------------------

class TestAutoCloseConsensusDiscussions:
    def test_closes_consensus_past_grace_period(self, project_with_db: Path):
        """Consensus discussion older than grace period gets closed."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        old = _make_old_ts(2)  # 2 hours ago > 60 min grace
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, 'consensus', ?)",
            ("d-old-consensus", "Old consensus topic", "[]", old),
        )
        conn.commit()
        conn.close()

        # Plant YAML with wrong status to prove it's ignored
        _create_yaml_decoys(project, "d-old-consensus", "active")

        n = _auto_close_consensus_discussions(str(project))
        assert n == 1, f"expected 1 closed, got {n}"

        # Verify SQLite was updated
        conn = get_connection(str(project))
        init_db(conn)
        disc = discussions_dao.get(conn, "d-old-consensus")
        assert disc is not None
        assert disc.status == "closed", f"expected closed, got {disc.status}"
        assert disc.closed_at is not None
        conn.close()

    def test_skips_recent_consensus(self, project_with_db: Path):
        """Consensus discussion within grace period is NOT closed."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        recent = now_iso()
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, 'consensus', ?)",
            ("d-recent-consensus", "Recent consensus", "[]", recent),
        )
        conn.commit()
        conn.close()

        n = _auto_close_consensus_discussions(str(project))
        assert n == 0, f"expected 0 closed (within grace), got {n}"

        conn = get_connection(str(project))
        init_db(conn)
        disc = discussions_dao.get(conn, "d-recent-consensus")
        assert disc.status == "consensus", "recent consensus should remain consensus"
        conn.close()

    def test_ignores_yaml_files(self, project_with_db: Path):
        """YAML files with status=consensus are NOT used as source of truth."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        conn.close()

        # Create only a YAML file with consensus status, NO SQLite row
        _create_yaml_decoys(project, "ghost-consensus", "consensus")

        # Touch the YAML to make mtime fresh (otherwise age calculation varies)
        yaml_path = project / ".superharness" / "discussions" / "ghost-consensus" / "state.yaml"
        os.utime(yaml_path, None)

        n = _auto_close_consensus_discussions(str(project))
        assert n == 0, "YAML-only consensus discussions must not be closed"


# ---------------------------------------------------------------------------
# _reconcile_discussion_contract
# ---------------------------------------------------------------------------

class TestReconcileDiscussionContract:
    def test_reconciles_archives_tasks_for_closed_discussion(self, project_with_db: Path):
        """Contract tasks linked to closed discussions in SQLite get archived."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)

        # Create a closed discussion in SQLite
        disc_id = "discuss-20250101T000000Z-12345-67890"
        now = now_iso()
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at, closed_at) "
            "VALUES (?, ?, ?, 'closed', ?, ?)",
            (disc_id, "Test discussion", "[]", now, now),
        )
        # Create a contract subtask linked to this discussion
        _raw_create_task(conn, f"{disc_id}/round-1", status="in_progress", now=now)
        # Write contract.yaml for test-mode state_reader visibility
        _write_contract_yaml(project, f"{disc_id}/round-1", status="in_progress")
        # Create an inbox item for it
        _raw_create_inbox(conn, "inbox-1", f"{disc_id}/round-1", now=now)
        conn.commit()
        conn.close()

        # Plant YAML with wrong status to prove it's ignored
        _create_yaml_decoys(project, disc_id, "active")

        n = _reconcile_discussion_contract(str(project))
        assert n == 1, f"expected 1 task updated, got {n}"

        # Verify task was archived via state_reader (canonical test-mode path)
        from superharness.engine.state_reader import get_tasks
        tasks = get_tasks(str(project))
        task = next((t for t in tasks if t.get("id") == f"{disc_id}/round-1"), None)
        assert task is not None, "task not found"
        assert task.get("status") == "archived", f"expected archived, got {task.get('status')}"
        conn.close()

    def test_reconciles_finds_terminal_from_sqlite_only(self, project_with_db: Path):
        """Multiple terminal statuses (cancelled, closed, consensus, deadlock, failed)
        in SQLite are all detected — YAML files with 'active' are ignored."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        now = now_iso()

        for st in ("cancelled", "closed", "consensus", "deadlock", "failed"):
            disc_id = f"disc-{st}"
            conn.execute(
                "INSERT INTO discussions (id, topic, owners, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (disc_id, f"Topic {st}", "[]", st, now),
            )
            _raw_create_task(conn, f"{disc_id}/round-1", status="in_progress", now=now)
            _write_contract_yaml(project, f"{disc_id}/round-1", status="in_progress")
            # Plant YAML with opposite status (active) to prove it's ignored
            _create_yaml_decoys(project, disc_id, "active")

        conn.commit()
        conn.close()

        n = _reconcile_discussion_contract(str(project))
        assert n == 5, f"expected 5 tasks archived, got {n}"
