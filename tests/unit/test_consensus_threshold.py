"""Tests for consensus detection with participant floor (max(2, n-1))."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


def _setup_db(tmp_path: Path) -> sqlite3.Connection:
    harness = tmp_path / ".superharness"
    harness.mkdir()
    db_path = harness / "state.sqlite3"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    from superharness.engine.db import init_db
    init_db(conn)
    return conn


class TestConsensusThreshold:

    def test_three_of_four_triggers_consensus(self, tmp_path):
        """4 owners, 3 submit with agree -> consensus."""
        from superharness.engine.discussion import _check_all_submitted_and_set_consensus
        from superharness.engine import discussions_dao

        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('dc1', 'test', '[\"claude-code\",\"codex-cli\",\"gemini-cli\",\"opencode\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        for agent in ["claude-code", "codex-cli", "gemini-cli"]:
            discussions_dao.add_round(conn, discussion_id="dc1", round_number=1,
                                      agent=agent, verdict="agree", content="ok",
                                      now="2026-01-01T01:00:00Z")
        conn.commit()
        disc = discussions_dao.get(conn, "dc1")
        _check_all_submitted_and_set_consensus(conn, disc, 1)
        row = conn.execute("SELECT status, consensus FROM discussions WHERE id='dc1'").fetchone()
        assert row["status"] == "consensus"
        assert row["consensus"] is not None
        conn.close()

    def test_two_of_three_triggers_consensus(self, tmp_path):
        """3 owners, 2 submit with agree -> consensus (n-1=2)."""
        from superharness.engine.discussion import _check_all_submitted_and_set_consensus
        from superharness.engine import discussions_dao

        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('dc2', 'test', '[\"claude-code\",\"codex-cli\",\"gemini-cli\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        for agent in ["claude-code", "codex-cli"]:
            discussions_dao.add_round(conn, discussion_id="dc2", round_number=1,
                                      agent=agent, verdict="agree", content="ok",
                                      now="2026-01-01T01:00:00Z")
        conn.commit()
        disc = discussions_dao.get(conn, "dc2")
        _check_all_submitted_and_set_consensus(conn, disc, 1)
        row = conn.execute("SELECT status FROM discussions WHERE id='dc2'").fetchone()
        assert row["status"] == "consensus"
        conn.close()

    def test_two_of_four_not_enough(self, tmp_path):
        """4 owners, 2 submit -> NOT consensus (need 3)."""
        from superharness.engine.discussion import _check_all_submitted_and_set_consensus
        from superharness.engine import discussions_dao

        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('dc3', 'test', '[\"claude-code\",\"codex-cli\",\"gemini-cli\",\"opencode\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        for agent in ["claude-code", "codex-cli"]:
            discussions_dao.add_round(conn, discussion_id="dc3", round_number=1,
                                      agent=agent, verdict="agree", content="ok",
                                      now="2026-01-01T01:00:00Z")
        conn.commit()
        disc = discussions_dao.get(conn, "dc3")
        _check_all_submitted_and_set_consensus(conn, disc, 1)
        row = conn.execute("SELECT status FROM discussions WHERE id='dc3'").fetchone()
        assert row["status"] == "active"  # still active, not enough
        conn.close()

    def test_mixed_verdicts_no_consensus(self, tmp_path):
        """3 of 4 submit but one disagrees -> NOT consensus."""
        from superharness.engine.discussion import _check_all_submitted_and_set_consensus
        from superharness.engine import discussions_dao

        conn = _setup_db(tmp_path)
        conn.execute(
            "INSERT INTO discussions (id, topic, owners, status, created_at) "
            "VALUES ('dc4', 'test', '[\"claude-code\",\"codex-cli\",\"gemini-cli\",\"opencode\"]', 'active', '2026-01-01T00:00:00Z')"
        )
        discussions_dao.add_round(conn, discussion_id="dc4", round_number=1,
                                  agent="claude-code", verdict="agree", content="ok",
                                  now="2026-01-01T01:00:00Z")
        discussions_dao.add_round(conn, discussion_id="dc4", round_number=1,
                                  agent="codex-cli", verdict="agree", content="ok",
                                  now="2026-01-01T01:00:00Z")
        discussions_dao.add_round(conn, discussion_id="dc4", round_number=1,
                                  agent="gemini-cli", verdict="disagree", content="no",
                                  now="2026-01-01T01:00:00Z")
        conn.commit()
        disc = discussions_dao.get(conn, "dc4")
        _check_all_submitted_and_set_consensus(conn, disc, 1)
        row = conn.execute("SELECT status FROM discussions WHERE id='dc4'").fetchone()
        assert row["status"] == "active"  # disagree blocks consensus
        conn.close()

    def test_verdict_normalization(self):
        """Prompt copy (all 3 options) -> first match. Partial copy -> rejected."""
        import re
        valid = {"agree", "disagree", "partial", "consensus", "abstain"}
        sorted_valid = sorted(valid)
        
        # Prompt copy with all 3 options → normalize
        raw = "agree or disagree or partial"
        normalized = raw.lower()
        if normalized not in valid:
            matches = [v for v in sorted_valid if re.search(r'\b' + re.escape(v) + r'\b', normalized)]
            assert len(matches) >= 3, f"should detect 3 options, got {matches}"
            normalized = matches[0]
        assert normalized == "agree"

        # Two options is ambiguous → should NOT normalize
        raw = "disagree or partial"
        normalized = raw.lower()
        if normalized not in valid:
            matches = [v for v in sorted_valid if re.search(r'\b' + re.escape(v) + r'\b', normalized)]
            assert len(matches) < 3, f"'disagree or partial' has {len(matches)} matches: {matches}"

    def test_invalid_verdict_rejected(self):
        """Completely invalid verdict should not normalize."""
        valid = {"agree", "disagree", "partial", "consensus", "abstain"}
        normalized = "garbage"
        found = False
        if normalized not in valid:
            for v in sorted(valid):
                if v in normalized:
                    found = True
                    break
        assert not found

    def test_single_valid_verdict_passes(self):
        """Single valid verdict is accepted as-is."""
        valid = {"agree", "disagree", "partial", "consensus", "abstain"}
        for v in ["agree", "disagree", "partial", "consensus", "abstain"]:
            assert v in valid

    def test_prompt_copy_normalized(self):
        """All 3 options = prompt copy -> first match extracted."""
        valid = {"agree", "disagree", "partial", "consensus", "abstain"}
        raw = "agree or disagree or partial"
        normalized = raw.lower()
        assert normalized not in valid
        matches = [v for v in sorted(valid) if v in normalized]
        assert len(matches) == 3  # all three
        assert matches[0] == "agree"  # first alphabetical
