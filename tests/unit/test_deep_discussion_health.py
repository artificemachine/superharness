"""Tests for _deep_discussion_health in status.py.

Verifies counts come from SQLite, never from stale YAML filesystem fallback.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import discussions_dao
from superharness.commands.status import _deep_discussion_health


@pytest.fixture
def project_with_db(tmp_path: Path) -> Path:
    """Project directory with initialized SQLite DB."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    return project


def populate_discussions(conn: sqlite3.Connection) -> None:
    """Create discussion rows matching real-world statuses (no current_round/max_rounds)."""
    now = now_iso()
    discussions_dao.create(conn, id="d-active-1", topic="Active A", owners=[], now=now)
    discussions_dao.create(conn, id="d-active-2", topic="Active B", owners=[], now=now)
    discussions_dao.create(conn, id="d-closed-1", topic="Closed X", owners=[], now=now)
    discussions_dao.create(conn, id="d-closed-2", topic="Closed Y", owners=[], now=now)
    discussions_dao.create(conn, id="d-closed-3", topic="Closed Z", owners=[], now=now)
    discussions_dao.create(conn, id="d-consensus-1", topic="Consensus R", owners=[], now=now)
    discussions_dao.create(conn, id="d-cancelled-1", topic="Cancelled Q", owners=[], now=now)
    discussions_dao.close(conn, "d-closed-1", consensus=None, now=now)
    discussions_dao.close(conn, "d-closed-2", consensus=None, now=now)
    discussions_dao.close(conn, "d-closed-3", consensus=None, now=now)
    discussions_dao.close(conn, "d-consensus-1", consensus="Go", now=now)
    # Set d-consensus-1 to consensus status manually (close sets it to closed)
    conn.execute("UPDATE discussions SET status='consensus' WHERE id='d-consensus-1'")
    conn.execute("UPDATE discussions SET status='cancelled' WHERE id='d-cancelled-1'")
    conn.commit()


def create_stale_yaml(project: Path) -> None:
    """Create YAML files that must NOT be counted (stale fallback data)."""
    disc_dir = project / ".superharness" / "discussions"
    for i in range(10):
        d = disc_dir / f"stale-disc-{i}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "state.yaml").write_text(
            "status: active\n"  # all claim active to inflate counts
            "topic: stale ghost\n"
        )


class TestDeepDiscussionHealth:
    def test_counts_from_sqlite_only(self, project_with_db: Path):
        """Counts must reflect SQLite, ignoring any stale YAML on disk."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        populate_discussions(conn)
        conn.close()

        # Plant stale YAML to verify it's NOT counted
        create_stale_yaml(project)

        result = _deep_discussion_health(str(project))
        counts = result["counts"]

        assert counts.get("active", 0) == 2, f"expected 2 active, got {counts}"
        assert counts.get("closed", 0) == 3, f"expected 3 closed, got {counts}"
        assert counts.get("consensus", 0) == 1, f"expected 1 consensus, got {counts}"
        assert counts.get("cancelled", 0) == 1, f"expected 1 cancelled, got {counts}"
        # Verify no stale YAML contamination
        assert sum(counts.values()) == 7, f"total should be 7, got {sum(counts.values())}"

    def test_consensus_unclosed_populated(self, project_with_db: Path):
        """Consensus-unclosed list must include the consensus row, without AttributeError."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        populate_discussions(conn)
        conn.close()

        result = _deep_discussion_health(str(project))

        consensus_ids = [d["id"] for d in result["consensus_unclosed"]]
        assert "d-consensus-1" in consensus_ids, f"consensus_unclosed missing d-consensus-1, got {consensus_ids}"

    def test_stale_active_detection(self, project_with_db: Path):
        """Stale active detection works when created_at is old."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        # Insert an active row with an old timestamp
        old_ts = "2025-01-01T00:00:00Z"
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            ("d-stale", "Very old discussion", "[]", old_ts),
        )
        conn.commit()
        conn.close()

        result = _deep_discussion_health(str(project))
        stale_ids = [d["id"] for d in result["stale_active"]]
        assert "d-stale" in stale_ids, f"stale_active missing d-stale, got {stale_ids}"

    def test_empty_project_returns_zero_counts(self, project_with_db: Path):
        """Empty DB returns zeroes, not YAML ghosts."""
        project = project_with_db
        conn = get_connection(str(project))
        init_db(conn)
        conn.close()

        # Plant stale YAML to verify it's ignored
        create_stale_yaml(project)

        result = _deep_discussion_health(str(project))
        counts = result["counts"]

        assert sum(counts.values()) == 0, f"expected zero counts, got {counts}"
        assert result["consensus_unclosed"] == []
        assert result["stale_active"] == []
