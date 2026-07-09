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


# ---------------------------------------------------------------------------
# Fix #4: cmd_submit_round rejects prompt-copy verdicts
# (BUGREPORT-discussion-consensus-single-participant)
# ---------------------------------------------------------------------------

class TestSubmitRejectsPromptCopyVerdict:
    """cmd_submit_round must reject verdicts that are unparsed prompt copies
    ('agree or disagree or partial') instead of silently normalizing to a
    random valid option."""

    def _setup_discussion_dir(self, project: Path, disc_id: str, participants: list[str]) -> Path:
        """Create a full discussion directory with DB so cmd_submit_round works."""
        conn = get_connection(str(project))
        init_db(conn)
        _setup_discussion(conn, disc_id, participants)

        # Create discussion directory on disk
        disc_dir = project / ".superharness" / "discussions" / disc_id
        disc_dir.mkdir(parents=True, exist_ok=True)
        conn.close()
        return disc_dir

    def test_rejects_prompt_copy_all_three_options(self, project_with_db: Path):
        """'agree or disagree or partial' (all 3 options) → SystemExit."""
        project = project_with_db
        disc_dir = self._setup_discussion_dir(
            project, "disc-prompt-copy", ["claude-code", "codex-cli"]
        )

        from superharness.engine.discussion import cmd_submit_round
        import io, sys

        old_stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            with pytest.raises(SystemExit) as exc_info:
                cmd_submit_round(
                    discussion_dir=str(disc_dir),
                    round_=1,
                    agent="codex-cli",
                    verdict="agree or disagree or partial",
                    position="test",
                )
            assert exc_info.value.code != 0, "must exit non-zero for prompt-copy verdict"
        finally:
            sys.stderr = old_stderr

    def test_accepts_valid_abstain(self, project_with_db: Path):
        """'abstain' → accepted (valid consensus vote)."""
        project = project_with_db
        disc_dir = self._setup_discussion_dir(
            project, "disc-valid-abstain", ["claude-code", "codex-cli"]
        )

        from superharness.engine.discussion import cmd_submit_round
        rc = cmd_submit_round(
            discussion_dir=str(disc_dir),
            round_=1,
            agent="codex-cli",
            verdict="abstain",
            position="test",
        )
        assert rc == 0

        # Verify submission landed
        conn = get_connection(str(project))
        init_db(conn)
        rounds = discussions_dao.get_rounds(conn, "disc-valid-abstain")
        submitted = [r for r in rounds if r.agent == "codex-cli"]
        assert len(submitted) == 1
        assert submitted[0].verdict == "abstain"
        conn.close()

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
