"""Cold-start native discussion discovery and acknowledgement tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from superharness.commands.discuss import cmd_pending, cmd_rounds
from superharness.commands.task import create as create_task
from superharness.engine import discussions_dao, inbox_dao
from superharness.engine.db import get_connection, init_db
from superharness.engine.discussion import cmd_submit_round


DISCUSSION_ID = "discuss-cold-start"
NOW = "2026-07-30T16:00:00Z"


def _seed_cold_start(
    project: Path,
    state_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    discussions_dir = project / ".superharness" / "discussions"
    discussion_dir = discussions_dir / DISCUSSION_ID
    discussion_dir.mkdir(parents=True)
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_root))

    conn = get_connection(str(project))
    try:
        init_db(conn)
        discussions_dao.create(
            conn,
            id=DISCUSSION_ID,
            topic="sender-first nonce COLD-START-42",
            owners=["claude-code", "codex-cli"],
            max_rounds=3,
            now=NOW,
        )
        conn.commit()
    finally:
        conn.close()

    assert create_task(
        project_dir=str(project),
        task_id=f"{DISCUSSION_ID}/round-1",
        title="Discussion round 1: sender-first nonce COLD-START-42",
        owner="claude-code",
        status="in_progress",
        project_path=str(project),
        workflow="discussion",
    ) == 0

    conn = get_connection(str(project))
    try:
        init_db(conn)
        for agent in ("claude-code", "codex-cli"):
            inbox_dao.enqueue(
                conn,
                id=f"inbox-{agent}",
                task_id=f"{DISCUSSION_ID}/round-1",
                target_agent=agent,
                project_path=str(project),
                type="discussion",
                now=NOW,
            )
        conn.commit()
    finally:
        conn.close()
    return discussion_dir


def test_pending_discovers_only_recipient_without_discussion_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    _seed_cold_start(project, tmp_path / "state", monkeypatch)
    capsys.readouterr()

    assert cmd_pending(str(project), "codex-cli", as_json=True) == 0

    pending = json.loads(capsys.readouterr().out)
    assert pending == [
        {
            "inbox_id": "inbox-codex-cli",
            "discussion_id": DISCUSSION_ID,
            "round": 1,
            "topic": "sender-first nonce COLD-START-42",
            "status": "pending",
            "participants": ["claude-code", "codex-cli"],
            "created_at": NOW,
        }
    ]


def test_manual_reply_acknowledges_shared_inbox_and_exposes_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project = tmp_path / "project"
    discussion_dir = _seed_cold_start(project, tmp_path / "state", monkeypatch)
    capsys.readouterr()

    assert cmd_submit_round(
        str(discussion_dir),
        round_=1,
        agent="codex-cli",
        verdict="partial",
        position="RECEIPT_ACK COLD-START-42",
    ) == 0
    submit_result = json.loads(capsys.readouterr().out)
    assert submit_result["acknowledged_inbox_ids"] == ["inbox-codex-cli"]

    conn = get_connection(str(project))
    try:
        init_db(conn)
        assert inbox_dao.get(conn, "inbox-codex-cli").status == "done"
        assert inbox_dao.get(conn, "inbox-claude-code").status == "pending"
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    finally:
        conn.close()

    assert cmd_rounds(
        str(project / ".superharness" / "discussions"),
        DISCUSSION_ID,
    ) == 0
    rounds_output = capsys.readouterr().out
    assert "codex-cli: verdict=partial" in rounds_output
    assert "RECEIPT_ACK COLD-START-42" in rounds_output
