"""Regression tests for auto-consensus verdict gate.

Bug: _check_all_submitted_and_set_consensus() closed the discussion as
'consensus' when any participant voted 'partial', because the gate only
blocked on 'disagree'. 'partial' means "not fully convinced" and must
advance to the next round, not close.

Fix: require ALL verdicts to be 'agree' or 'consensus' before auto-closing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import discussions_dao
from superharness.engine.discussion import _check_all_submitted_and_set_consensus


@pytest.fixture
def project_with_db(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    (project / ".superharness").mkdir()
    return project


def _setup_discussion(conn, disc_id: str, participants: list[str]) -> object:
    discussions_dao.create(
        conn,
        id=disc_id,
        topic="Test topic",
        owners=participants,
        task_id=None,
        now=now_iso(),
    )
    conn.commit()
    return discussions_dao.get(conn, disc_id)


def _submit(conn, disc_id: str, round_: int, agent: str, verdict: str) -> None:
    conn.execute(
        "INSERT INTO discussion_rounds (discussion_id, round_number, agent, content, verdict, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (disc_id, round_, agent, f"Position by {agent}", verdict, now_iso()),
    )
    conn.commit()


class TestPartialDoesNotTriggerAutoConsensus:
    def test_all_agree_closes_as_consensus(self, project_with_db: Path):
        """All 'agree' verdicts must auto-close as consensus."""
        conn = get_connection(str(project_with_db))
        init_db(conn)
        disc = _setup_discussion(conn, "disc-agree", ["claude-code", "gemini-cli"])
        _submit(conn, disc.id, 1, "claude-code", "agree")
        _submit(conn, disc.id, 1, "gemini-cli", "agree")

        _check_all_submitted_and_set_consensus(conn, disc, 1)
        conn.commit()

        updated = discussions_dao.get(conn, disc.id)
        conn.close()
        assert updated.status == "consensus"

    def test_all_consensus_verdicts_closes_as_consensus(self, project_with_db: Path):
        """All 'consensus' verdicts must auto-close as consensus."""
        conn = get_connection(str(project_with_db))
        init_db(conn)
        disc = _setup_discussion(conn, "disc-all-consensus", ["claude-code", "gemini-cli"])
        _submit(conn, disc.id, 1, "claude-code", "consensus")
        _submit(conn, disc.id, 1, "gemini-cli", "consensus")

        _check_all_submitted_and_set_consensus(conn, disc, 1)
        conn.commit()

        updated = discussions_dao.get(conn, disc.id)
        conn.close()
        assert updated.status == "consensus"

    def test_partial_vote_keeps_discussion_active(self, project_with_db: Path):
        """'partial' verdict must NOT auto-close — discussion stays active for next round."""
        conn = get_connection(str(project_with_db))
        init_db(conn)
        disc = _setup_discussion(conn, "disc-partial", ["claude-code", "gemini-cli", "opencode"])
        _submit(conn, disc.id, 1, "claude-code", "consensus")
        _submit(conn, disc.id, 1, "gemini-cli", "partial")
        _submit(conn, disc.id, 1, "opencode", "partial")

        _check_all_submitted_and_set_consensus(conn, disc, 1)
        conn.commit()

        updated = discussions_dao.get(conn, disc.id)
        conn.close()
        assert updated.status == "active", (
            "Discussion with partial votes must stay active, not auto-close as consensus"
        )

    def test_disagree_vote_keeps_discussion_active(self, project_with_db: Path):
        """'disagree' verdict must NOT auto-close — existing behaviour preserved."""
        conn = get_connection(str(project_with_db))
        init_db(conn)
        disc = _setup_discussion(conn, "disc-disagree", ["claude-code", "gemini-cli"])
        _submit(conn, disc.id, 1, "claude-code", "agree")
        _submit(conn, disc.id, 1, "gemini-cli", "disagree")

        _check_all_submitted_and_set_consensus(conn, disc, 1)
        conn.commit()

        updated = discussions_dao.get(conn, disc.id)
        conn.close()
        assert updated.status == "active"

    def test_mixed_agree_and_partial_keeps_active(self, project_with_db: Path):
        """agree + partial must keep discussion active."""
        conn = get_connection(str(project_with_db))
        init_db(conn)
        disc = _setup_discussion(conn, "disc-mixed", ["claude-code", "gemini-cli"])
        _submit(conn, disc.id, 1, "claude-code", "agree")
        _submit(conn, disc.id, 1, "gemini-cli", "partial")

        _check_all_submitted_and_set_consensus(conn, disc, 1)
        conn.commit()

        updated = discussions_dao.get(conn, disc.id)
        conn.close()
        assert updated.status == "active"

    def test_not_all_submitted_does_not_close(self, project_with_db: Path):
        """Only one of two participants submitted — must not auto-close."""
        conn = get_connection(str(project_with_db))
        init_db(conn)
        disc = _setup_discussion(conn, "disc-partial-submit", ["claude-code", "gemini-cli"])
        _submit(conn, disc.id, 1, "claude-code", "agree")

        _check_all_submitted_and_set_consensus(conn, disc, 1)
        conn.commit()

        updated = discussions_dao.get(conn, disc.id)
        conn.close()
        assert updated.status == "active"
