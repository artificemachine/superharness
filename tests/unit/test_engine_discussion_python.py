"""Python-native tests for superharness.engine.discussion."""
from __future__ import annotations

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


def test_start_creates_state_yaml(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    info = _start(discussions_dir)
    assert info["status"] == "active"
    assert info["current_round"] == 1
    disc_dir = Path(info["discussion_dir"])
    assert (disc_dir / "state.yaml").exists()


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


def test_list_discussions(tmp_path: Path) -> None:
    discussions_dir = tmp_path / "discussions"
    discussions_dir.mkdir()
    _start(discussions_dir, "Topic A")
    _start(discussions_dir, "Topic B")
    r = _run_discussion("list", ["--discussions-dir", str(discussions_dir)])
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data) == 2


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
