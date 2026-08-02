"""Race-condition guards for discussion round submission.

Two TOCTOU windows exist in cmd_submit_round because Python sqlite3's
default isolation issues the implicit BEGIN only before the first write:
every pre-check (status gate, duplicate-submit check) runs in autocommit,
outside the write lock.

1. discussion_rounds had no unique constraint, so two concurrent submits
   by the same agent could both pass the read-check and both INSERT.
2. A straggler submit racing the final submitter could pass the
   status=='active' gate, then land its round in a just-consensus'd
   discussion and re-fire the consensus transition (re-upserting the
   impl-* task and resetting its status).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.engine import discussions_dao
from superharness.engine.db import get_connection, init_db
from superharness.engine.discussion import (
    _check_all_submitted_and_set_consensus,
    cmd_submit_round,
)
from superharness.engine.errors import OperationError
from superharness.engine.state_errors import StateError


DISCUSSION_ID = "discuss-race-guards"
NOW = "2026-07-31T10:00:00Z"


def _seed(project: Path, state_root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    discussion_dir = project / ".superharness" / "discussions" / DISCUSSION_ID
    discussion_dir.mkdir(parents=True)
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_root))
    conn = get_connection(str(project))
    try:
        init_db(conn)
        discussions_dao.create(
            conn,
            id=DISCUSSION_ID,
            topic="race guard test",
            owners=["claude-code", "codex-cli"],
            max_rounds=3,
            now=NOW,
        )
        conn.commit()
    finally:
        conn.close()
    return discussion_dir


def test_duplicate_round_insert_rejected_at_dao_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DB itself must reject a second round row for the same
    (discussion, round, agent) — the CLI read-check alone is a TOCTOU."""
    project = tmp_path / "project"
    _seed(project, tmp_path / "state", monkeypatch)

    conn = get_connection(str(project))
    try:
        init_db(conn)
        discussions_dao.add_round(
            conn,
            discussion_id=DISCUSSION_ID,
            round_number=1,
            agent="codex-cli",
            content="first",
            verdict="partial",
            now=NOW,
        )
        with pytest.raises(StateError):
            discussions_dao.add_round(
                conn,
                discussion_id=DISCUSSION_ID,
                round_number=1,
                agent="codex-cli",
                content="duplicate",
                verdict="partial",
                now=NOW,
            )
        conn.rollback()
        rows = discussions_dao.get_rounds(conn, DISCUSSION_ID)
        assert len([r for r in rows if r.agent == "codex-cli"]) <= 1
    finally:
        conn.close()


def test_advance_markers_not_blocked_by_unique_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_advance bookkeeping rows are not agent submissions and must stay
    exempt from the uniqueness rule."""
    project = tmp_path / "project"
    _seed(project, tmp_path / "state", monkeypatch)

    conn = get_connection(str(project))
    try:
        init_db(conn)
        for _ in range(2):
            discussions_dao.add_round(
                conn,
                discussion_id=DISCUSSION_ID,
                round_number=2,
                agent="_advance",
                content=None,
                verdict=None,
                now=NOW,
            )
        conn.commit()
        markers = [
            r for r in discussions_dao.get_rounds(conn, DISCUSSION_ID)
            if r.agent == "_advance"
        ]
        assert len(markers) == 2
    finally:
        conn.close()


def test_submit_rechecks_status_inside_write_txn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Simulate the race: discussion flips active→consensus between the
    autocommit pre-gate read and the write transaction. The submit must
    fail cleanly and persist nothing."""
    project = tmp_path / "project"
    discussion_dir = _seed(project, tmp_path / "state", monkeypatch)

    real_get = discussions_dao.get
    calls = {"n": 0}

    def racing_get(conn, disc_id):
        import dataclasses

        row = real_get(conn, disc_id)
        calls["n"] += 1
        if row is not None and calls["n"] >= 2:
            row = dataclasses.replace(row, status="consensus")
        return row

    monkeypatch.setattr(
        "superharness.engine.discussion.discussions_dao.get", racing_get
    )

    with pytest.raises(OperationError):
        cmd_submit_round(
            str(discussion_dir),
            round_=1,
            agent="codex-cli",
            verdict="partial",
            position="straggler racing consensus",
        )
    assert calls["n"] >= 2, "in-transaction status recheck never ran"

    conn = get_connection(str(project))
    try:
        init_db(conn)
        rows = [
            r for r in discussions_dao.get_rounds(conn, DISCUSSION_ID)
            if r.agent == "codex-cli"
        ]
        assert rows == [], "racing submit must not persist a round row"
    finally:
        conn.close()


def test_consensus_transition_fires_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The consensus UPDATE must be guarded on status='active' so a
    re-entrant check cannot re-fire task creation on an already
    consensus'd discussion."""
    project = tmp_path / "project"
    _seed(project, tmp_path / "state", monkeypatch)

    conn = get_connection(str(project))
    try:
        init_db(conn)
        for agent in ("claude-code", "codex-cli"):
            discussions_dao.add_round(
                conn,
                discussion_id=DISCUSSION_ID,
                round_number=1,
                agent=agent,
                content=f"{agent} agrees",
                verdict="agree",
                now=NOW,
            )
        conn.execute(
            "UPDATE discussions SET status='consensus' WHERE id=?", (DISCUSSION_ID,)
        )
        conn.commit()

        created_calls = []
        monkeypatch.setattr(
            "superharness.engine.discussion._create_consensus_task",
            lambda *a, **k: created_calls.append(1),
        )
        disc = discussions_dao.get(conn, DISCUSSION_ID)
        _check_all_submitted_and_set_consensus(conn, disc, 1, project_dir=str(project))
        conn.commit()
        assert created_calls == [], (
            "consensus transition re-fired on an already consensus'd discussion"
        )
    finally:
        conn.close()


def test_pre_migration_backup_fires_without_project_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """172 of 175 init_db callers omit project_dir, which silently disabled
    the pre-migration backup (2026-06-07 audit Finding 41). The backup must
    now derive the DB file from the connection itself."""
    import os

    from superharness.engine import db as db_mod

    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "state"))
    project = tmp_path / "project"
    project.mkdir()

    conn = db_mod.get_connection(str(project))
    db_mod.init_db(conn)  # note: no project_dir — the common caller shape
    conn.execute("DROP INDEX IF EXISTS idx_disc_rounds_unique_submission")
    conn.execute("DELETE FROM schema_migrations WHERE version = ?",
                 (db_mod.CURRENT_SCHEMA_VERSION,))
    conn.execute(f"PRAGMA user_version = {db_mod.CURRENT_SCHEMA_VERSION - 1}")
    conn.commit()
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn.close()

    conn = db_mod.get_connection(str(project))
    db_mod.init_db(conn)  # re-runs the last migration, still no project_dir
    conn.close()

    expected = f"{db_path}.bak.v{db_mod.CURRENT_SCHEMA_VERSION - 1}"
    assert os.path.isfile(expected), (
        "pre-migration backup did not fire for a project_dir-less init_db"
    )
