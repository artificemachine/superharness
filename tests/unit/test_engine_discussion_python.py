"""Python-native tests for superharness.engine.discussion."""
from __future__ import annotations
import pytest

import json
import subprocess
import sys
from pathlib import Path


PYTHON = sys.executable


def _run_discussion(cmd: str, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.engine.discussion", cmd] + args,
        capture_output=True,
        text=True,
        check=False,
    )


def _start(discussions_dir: Path, topic: str = "Should we proceed?") -> dict:
    r = _run_discussion("start", [
        "--discussions-dir", str(discussions_dir),
        "--topic", topic,
        "--participant", "agent-a",
        "--participant", "agent-b",
        "--project", "/test/project",
    ])
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_start_creates_state_yaml(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    assert info["status"] == "active"
    assert info["current_round"] == 1
    disc_dir = Path(info["discussion_dir"])
    assert (disc_dir / "state.yaml").exists()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_submit_round_creates_position_file(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    r = _run_discussion("submit_round", [
        "--discussion-dir", disc_dir,
        "--round", "1",
        "--agent", "agent-a",
        "--verdict", "agree",
        "--position", "I think we should proceed.",
    ])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["submitted"] is True
    assert (Path(disc_dir) / "round-1-agent-a.yaml").exists()


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_check_round_all_done(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    for agent in ("agent-a", "agent-b"):
        _run_discussion("submit_round", [
            "--discussion-dir", disc_dir,
            "--round", "1", "--agent", agent,
            "--verdict", "agree", "--position", "yes",
        ])
    r = _run_discussion("check_round", ["--discussion-dir", disc_dir, "--round", "1"])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["complete"] is True
    assert set(result["agents_done"]) == {"agent-a", "agent-b"}
    assert result["agents_pending"] == []


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_check_round_pending(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    _run_discussion("submit_round", [
        "--discussion-dir", disc_dir,
        "--round", "1", "--agent", "agent-a",
        "--verdict", "agree", "--position", "yes",
    ])
    r = _run_discussion("check_round", ["--discussion-dir", disc_dir, "--round", "1"])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["complete"] is False
    assert "agent-b" in result["agents_pending"]


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_check_consensus_agree(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    for agent in ("agent-a", "agent-b"):
        _run_discussion("submit_round", [
            "--discussion-dir", disc_dir,
            "--round", "1", "--agent", agent,
            "--verdict", "agree", "--position", "yes",
        ])
    r = _run_discussion("check_consensus", ["--discussion-dir", disc_dir])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["consensus"] is True


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_check_consensus_disagree(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    _run_discussion("submit_round", [
        "--discussion-dir", disc_dir,
        "--round", "1", "--agent", "agent-a",
        "--verdict", "agree", "--position", "yes",
    ])
    _run_discussion("submit_round", [
        "--discussion-dir", disc_dir,
        "--round", "1", "--agent", "agent-b",
        "--verdict", "disagree", "--position", "no",
    ])
    r = _run_discussion("check_consensus", ["--discussion-dir", disc_dir])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["consensus"] is False


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_advance_consensus_closes(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    for agent in ("agent-a", "agent-b"):
        _run_discussion("submit_round", [
            "--discussion-dir", disc_dir,
            "--round", "1", "--agent", agent,
            "--verdict", "agree", "--position", "yes",
        ])
    r = _run_discussion("advance", ["--discussion-dir", disc_dir])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["action"] == "closed"
    assert result["reason"] == "consensus"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_advance_no_consensus_advances_round(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    _run_discussion("submit_round", [
        "--discussion-dir", disc_dir,
        "--round", "1", "--agent", "agent-a",
        "--verdict", "agree", "--position", "yes",
    ])
    _run_discussion("submit_round", [
        "--discussion-dir", disc_dir,
        "--round", "1", "--agent", "agent-b",
        "--verdict", "disagree", "--position", "no",
    ])
    r = _run_discussion("advance", ["--discussion-dir", disc_dir])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["action"] == "advanced"
    assert result["next_round"] == 2


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_advance_max_rounds_closes(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    # Start with max_rounds=1
    r_start = _run_discussion("start", [
        "--discussions-dir", str(discussions_dir),
        "--topic", "test",
        "--participant", "agent-a",
        "--participant", "agent-b",
        "--project", "/test",
        "--max-rounds", "1",
    ])
    info = json.loads(r_start.stdout)
    disc_dir = info["discussion_dir"]
    # Both disagree
    for agent in ("agent-a", "agent-b"):
        _run_discussion("submit_round", [
            "--discussion-dir", disc_dir,
            "--round", "1", "--agent", agent,
            "--verdict", "disagree", "--position", "no",
        ])
    r = _run_discussion("advance", ["--discussion-dir", disc_dir])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["action"] == "closed"
    assert result["reason"] == "max_rounds_reached"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_list_discussions(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    _start(discussions_dir, "Topic A")
    _start(discussions_dir, "Topic B")
    r = _run_discussion("list", ["--discussions-dir", str(discussions_dir)])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data) == 2


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_close_discussion(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    disc_dir = info["discussion_dir"]
    r = _run_discussion("close", ["--discussion-dir", disc_dir, "--outcome", "cancelled"])
    assert r.returncode == 0
    result = json.loads(r.stdout)
    assert result["closed"] is True
    assert result["outcome"] == "cancelled"
    # Verify state file updated
    r2 = _run_discussion("status", ["--discussion-dir", disc_dir])
    state = json.loads(r2.stdout)
    assert state["status"] == "cancelled"


# ── Iter 13 RED: consensus task project_path must be the real project dir ─────

def test_consensus_task_project_path_correct(tmp_path):
    """_create_consensus_task must use the real project directory, not the XDG hash dir.

    RED: project_dir is derived from PRAGMA database_list, which returns the
    XDG path like ~/.local/state/superharness/<hash>/state.db. Taking dirname
    twice gives ~/.local/state/superharness/<hash>, not the project directory.
    GREEN: pass project_dir as a parameter to _create_consensus_task.
    """
    import sqlite3
    import sys
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao, tasks_dao

    project = str(tmp_path / "real_project")
    import os
    os.makedirs(os.path.join(project, ".superharness"), exist_ok=True)

    conn = get_connection(project)
    init_db(conn, project_dir=project)

    # Insert a minimal discussion
    disc_id = "discuss-projpath-test20260607T000000Z-1-111111111"
    now = "2026-06-07T00:00:00Z"
    conn.execute(
        "INSERT INTO discussions (id, topic, status, owners, created_at) VALUES (?,?,?,?,?)",
        (disc_id, "Refactor auth module", "open", '["claude-code"]', now),
    )
    # Insert a round with a non-agree verdict so _create_consensus_task creates tasks
    conn.execute(
        "INSERT INTO discussion_rounds (discussion_id, round_number, agent, verdict, created_at) "
        "VALUES (?,?,?,?,?)",
        (disc_id, 1, "claude-code", "partial", now),
    )
    conn.commit()

    from superharness.engine.discussion import _create_consensus_task
    disc_row = discussions_dao.DiscussionRow(
        id=disc_id,
        topic="Refactor auth module",
        status="open",
        owners=["claude-code"],
        consensus=None,
        created_at=now,
        closed_at=None,
        task_id=None,
    )
    _create_consensus_task(conn, disc_row, 1, {"claude-code"}, project_dir=project)

    # The consensus task should have project_path = the real project dir
    task_id = f"impl-{disc_id[:30]}"
    row = conn.execute("SELECT project_path FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row is not None, f"Consensus task '{task_id}' was not created"
    assert row["project_path"] == project, (
        f"Consensus task project_path is {row['project_path']!r}, expected real project {project!r}. "
        "Pass project_dir as a parameter to _create_consensus_task."
    )
    conn.close()


# ── Iter 14 RED: max_rounds must be persisted and honored ─────────────────────

def test_max_rounds_honored(tmp_path):
    """cmd_advance must close the discussion after max_rounds rounds.

    RED: max_rounds is hardcoded to 3 in cmd_advance; --max-rounds is accepted
    but ignored. GREEN: store max_rounds in the discussions table and read it
    in cmd_advance.
    """
    import json as _json
    import sqlite3
    import os as _os
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    project = str(tmp_path / "proj")
    _os.makedirs(_os.path.join(project, ".superharness"))
    conn = get_connection(project)
    init_db(conn, project_dir=project)

    disc_id = "discuss-maxrounds-test20260607T000000Z-1-111111111"
    now = "2026-06-07T00:00:00Z"

    # Start discussion with max_rounds=2
    disc_dir = _os.path.join(project, ".superharness", "discussions", disc_id)
    _os.makedirs(disc_dir, exist_ok=True)

    from superharness.engine.discussion import cmd_start
    # cmd_start creates the discussion
    rc = cmd_start(
        discussions_dir=_os.path.join(project, ".superharness", "discussions"),
        topic="Should we refactor auth?",
        participants=["claude-code"],
        max_rounds=2,
        task_id=None,
        project=project,
        created_by="owner",
    )
    assert rc == 0

    # Fetch the stored max_rounds
    disc = discussions_dao.get(conn, disc_id if False else
        conn.execute("SELECT id FROM discussions ORDER BY created_at DESC LIMIT 1").fetchone()[0])
    stored_max = conn.execute(
        "SELECT max_rounds FROM discussions ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert stored_max is not None, (
        "No 'max_rounds' column found in discussions table. "
        "Add max_rounds INTEGER NOT NULL DEFAULT 3 via migration."
    )
    assert stored_max[0] == 2, (
        f"max_rounds stored as {stored_max[0]!r}, expected 2. "
        "cmd_start must persist the --max-rounds value."
    )
    conn.close()
