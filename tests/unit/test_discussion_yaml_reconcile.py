"""Regression tests for YAML→SQLite submission reconciliation in cmd_advance.

Bug: check_round counted a round-N-<agent>.yaml file on disk as "submitted"
(Bug G fix), but cmd_advance only queried SQLite. When an agent wrote its
YAML but the DB row was absent (write_file blocked, crash after write, etc.),
check_round returned complete=true while advance exited "Round N is not
complete yet". The dispatcher saw advance fail, fell to the else branch,
found no agents_pending (YAML satisfied check_round), and enqueued nobody.
The discussion was permanently stuck.

Fix: _reconcile_yaml_submissions() is called inside cmd_advance before the
completion check. It inserts any missing SQLite rows from on-disk YAMLs so
both views agree at the moment of state transition.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import discussions_dao
from superharness.engine.discussion import (
    _reconcile_yaml_submissions,
    cmd_advance,
    cmd_check_round,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / ".superharness" / "discussions").mkdir(parents=True)
    return proj


def _make_db(project: Path):
    conn = get_connection(str(project))
    init_db(conn)
    return conn


def _create_discussion(conn, project: Path, disc_id: str, participants: list[str]):
    discussions_dao.create(
        conn,
        id=disc_id,
        topic="test topic",
        owners=participants,
        task_id=None,
        now=now_iso(),
    )
    conn.commit()
    return discussions_dao.get(conn, disc_id)


def _disc_dir(project: Path, disc_id: str) -> Path:
    return project / ".superharness" / "discussions" / disc_id


def _write_yaml(project: Path, disc_id: str, round_: int, agent: str,
                verdict: str = "agree", position: str = "") -> Path:
    d = _disc_dir(project, disc_id)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"round-{round_}-{agent}.yaml"
    path.write_text(yaml.dump({
        "discussion_id": disc_id,
        "round": round_,
        "agent": agent,
        "verdict": verdict,
        "position": position or f"Position by {agent}",
    }))
    return path


def _register_in_db(conn, disc_id: str, round_: int, agent: str, verdict: str = "agree"):
    conn.execute(
        "INSERT INTO discussion_rounds "
        "(discussion_id, round_number, agent, content, verdict, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (disc_id, round_, agent, f"Position by {agent}", verdict, now_iso()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# _reconcile_yaml_submissions unit tests
# ---------------------------------------------------------------------------

class TestReconcileYamlSubmissions:
    def test_inserts_missing_yaml_submission(self, project: Path):
        """YAML file present but no DB row → row inserted after reconcile."""
        conn = _make_db(project)
        disc_id = "disc-reconcile-insert"
        disc = _create_discussion(conn, project, disc_id, ["agent-a", "agent-b"])
        _register_in_db(conn, disc_id, 1, "agent-a", "agree")
        _write_yaml(project, disc_id, 1, "agent-b", verdict="agree")

        reconciled = _reconcile_yaml_submissions(
            conn, disc, str(_disc_dir(project, disc_id)), 1
        )
        conn.commit()

        assert reconciled == ["agent-b"], "agent-b should have been reconciled"
        rounds = discussions_dao.get_rounds(conn, disc_id)
        agents_in_db = {r.agent for r in rounds if r.round_number == 1}
        assert "agent-b" in agents_in_db, "agent-b must now have a DB row"
        conn.close()

    def test_preserves_verdict_from_yaml(self, project: Path):
        """Reconciled row must carry the verdict from the YAML file."""
        conn = _make_db(project)
        disc_id = "disc-reconcile-verdict"
        disc = _create_discussion(conn, project, disc_id, ["agent-a"])
        _write_yaml(project, disc_id, 1, "agent-a", verdict="partial")

        _reconcile_yaml_submissions(
            conn, disc, str(_disc_dir(project, disc_id)), 1
        )
        conn.commit()

        rounds = discussions_dao.get_rounds(conn, disc_id)
        row = next(r for r in rounds if r.agent == "agent-a" and r.round_number == 1)
        assert row.verdict == "partial"
        conn.close()

    def test_skips_already_registered_agents(self, project: Path):
        """Agents already in SQLite must not be re-inserted or overwritten."""
        conn = _make_db(project)
        disc_id = "disc-reconcile-skip"
        disc = _create_discussion(conn, project, disc_id, ["agent-a"])
        _register_in_db(conn, disc_id, 1, "agent-a", "disagree")
        # YAML says agree — DB row says disagree; reconcile must not overwrite
        _write_yaml(project, disc_id, 1, "agent-a", verdict="agree")

        reconciled = _reconcile_yaml_submissions(
            conn, disc, str(_disc_dir(project, disc_id)), 1
        )
        conn.commit()

        assert reconciled == [], "No reconciliation expected when DB row already exists"
        rounds = discussions_dao.get_rounds(conn, disc_id)
        row = next(r for r in rounds if r.agent == "agent-a" and r.round_number == 1)
        assert row.verdict == "disagree", "Existing DB verdict must be preserved"
        conn.close()

    def test_no_yaml_no_insert(self, project: Path):
        """Missing YAML and missing DB row → nothing inserted."""
        conn = _make_db(project)
        disc_id = "disc-reconcile-noop"
        disc = _create_discussion(conn, project, disc_id, ["agent-a"])

        reconciled = _reconcile_yaml_submissions(
            conn, disc, str(_disc_dir(project, disc_id)), 1
        )
        conn.commit()

        assert reconciled == []
        rounds = discussions_dao.get_rounds(conn, disc_id)
        assert not any(r.agent == "agent-a" and r.round_number == 1 for r in rounds)
        conn.close()

    def test_bad_yaml_does_not_crash(self, project: Path):
        """Corrupt YAML must be silently skipped, not raise."""
        conn = _make_db(project)
        disc_id = "disc-reconcile-corrupt"
        disc = _create_discussion(conn, project, disc_id, ["agent-a"])
        bad_path = _disc_dir(project, disc_id) / "round-1-agent-a.yaml"
        bad_path.parent.mkdir(parents=True, exist_ok=True)
        bad_path.write_text(": this is: not: valid: yaml: ][")

        reconciled = _reconcile_yaml_submissions(
            conn, disc, str(_disc_dir(project, disc_id)), 1
        )
        assert reconciled == [], "Corrupt YAML must not crash reconcile"
        conn.close()


# ---------------------------------------------------------------------------
# cmd_advance integration tests (the stuck-discussion scenario)
# ---------------------------------------------------------------------------

class TestCmdAdvanceReconciles:
    def _make_discussion_dir(self, project: Path, disc_id: str) -> str:
        d = _disc_dir(project, disc_id)
        d.mkdir(parents=True, exist_ok=True)
        return str(d)

    def test_advance_succeeds_when_submissions_are_yaml_only(self, project: Path):
        """cmd_advance must succeed even when all submissions are YAML-only
        (no DB rows) — the stuck-discussion scenario."""
        import io
        import contextlib

        conn = _make_db(project)
        disc_id = "disc-adv-yaml-only"
        _create_discussion(conn, project, disc_id, ["agent-a", "agent-b"])
        conn.close()

        disc_dir = self._make_discussion_dir(project, disc_id)
        _write_yaml(project, disc_id, 1, "agent-a", verdict="agree")
        _write_yaml(project, disc_id, 1, "agent-b", verdict="agree")

        # Before fix: cmd_advance exited "Round 1 is not complete yet" (exit 1)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_advance(disc_dir)

        assert rc == 0, f"cmd_advance must return 0; stdout: {out.getvalue()}"
        result = json.loads(out.getvalue())
        assert result["action"] in ("advanced", "closed"), result

    def test_advance_with_mixed_db_and_yaml_submissions(self, project: Path):
        """One agent in DB, one YAML-only → advance must reconcile and proceed."""
        import io
        import contextlib

        conn = _make_db(project)
        disc_id = "disc-adv-mixed"
        _create_discussion(conn, project, disc_id, ["agent-a", "agent-b"])
        _register_in_db(conn, disc_id, 1, "agent-a", "agree")
        conn.close()

        disc_dir = self._make_discussion_dir(project, disc_id)
        _write_yaml(project, disc_id, 1, "agent-b", verdict="agree")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cmd_advance(disc_dir)

        assert rc == 0
        result = json.loads(out.getvalue())
        assert result["action"] in ("advanced", "closed")

    def test_advance_still_fails_when_truly_incomplete(self, project: Path):
        """Round genuinely incomplete (no YAML, no DB) must still exit non-zero."""
        conn = _make_db(project)
        disc_id = "disc-adv-incomplete"
        _create_discussion(conn, project, disc_id, ["agent-a", "agent-b"])
        _register_in_db(conn, disc_id, 1, "agent-a", "agree")
        conn.close()

        disc_dir = self._make_discussion_dir(project, disc_id)
        # agent-b has neither YAML nor DB row → incomplete

        with pytest.raises(SystemExit) as exc_info:
            cmd_advance(disc_dir)
        assert exc_info.value.code != 0

    def test_check_round_and_advance_agree_after_yaml_only_submit(self, project: Path):
        """check_round returning complete=true must not contradict cmd_advance
        when submissions are YAML-only (the core stuck-discussion invariant)."""
        import io
        import contextlib

        conn = _make_db(project)
        disc_id = "disc-adv-invariant"
        _create_discussion(conn, project, disc_id, ["agent-a", "agent-b"])
        conn.close()

        disc_dir = self._make_discussion_dir(project, disc_id)
        _write_yaml(project, disc_id, 1, "agent-a", verdict="agree")
        _write_yaml(project, disc_id, 1, "agent-b", verdict="agree")

        # check_round says complete
        check_out = io.StringIO()
        with contextlib.redirect_stdout(check_out):
            cmd_check_round(disc_dir, 1)
        check = json.loads(check_out.getvalue())
        assert check["complete"] is True, "check_round must see both YAMLs"

        # advance must also succeed (not contradict check_round)
        adv_out = io.StringIO()
        with contextlib.redirect_stdout(adv_out):
            rc = cmd_advance(disc_dir)
        assert rc == 0, (
            "cmd_advance must not exit non-zero when check_round says complete. "
            "This was the stuck-discussion bug."
        )
