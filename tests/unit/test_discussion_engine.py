from __future__ import annotations

import json
from pathlib import Path

from tests.helpers import run_cmd


def _run_engine(repo_root: Path, args: list[str]):
    return run_cmd(["ruby", str(repo_root / "engine" / "discussion.rb")] + args, cwd=repo_root)


def _start_discussion(repo_root: Path, tmp_path: Path, *, max_rounds: int = 2):
    project = tmp_path / f"proj-discussion-{max_rounds}"
    discussions_dir = project / ".superharness" / "discussions"
    discussions_dir.mkdir(parents=True, exist_ok=True)

    started = _run_engine(
        repo_root,
        [
            "start",
            "--discussions-dir",
            str(discussions_dir),
            "--topic",
            "Unit test discussion",
            "--participant",
            "claude-code",
            "--participant",
            "codex-cli",
            "--max-rounds",
            str(max_rounds),
            "--project",
            str(project),
        ],
    )
    assert started.returncode == 0, started.stderr
    data = json.loads(started.stdout)
    return project, Path(data["discussion_dir"])


def test_discussion_engine_closes_on_consensus(repo_root, tmp_path) -> None:
    _, discussion_dir = _start_discussion(repo_root, tmp_path, max_rounds=3)

    s1 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "agree",
            "--position",
            "I agree.",
        ],
    )
    assert s1.returncode == 0, s1.stderr

    s2 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "codex-cli",
            "--verdict",
            "agree",
            "--position",
            "I also agree.",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    advanced = _run_engine(repo_root, ["advance", "--discussion-dir", str(discussion_dir)])
    assert advanced.returncode == 0, advanced.stderr
    advanced_json = json.loads(advanced.stdout)
    assert advanced_json["action"] == "closed"
    assert advanced_json["reason"] == "consensus"

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "consensus"
    assert status_json["consensus_round"] == 1
    assert status_json["closed_at"]


def test_discussion_engine_closes_without_consensus_at_max_rounds(repo_root, tmp_path) -> None:
    _, discussion_dir = _start_discussion(repo_root, tmp_path, max_rounds=1)

    s1 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "agree",
            "--position",
            "Looks good.",
        ],
    )
    assert s1.returncode == 0, s1.stderr

    s2 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "codex-cli",
            "--verdict",
            "disagree",
            "--position",
            "Not aligned.",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    advanced = _run_engine(repo_root, ["advance", "--discussion-dir", str(discussion_dir)])
    assert advanced.returncode == 0, advanced.stderr
    advanced_json = json.loads(advanced.stdout)
    assert advanced_json["action"] == "closed"
    assert advanced_json["reason"] == "max_rounds_reached"

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "no_consensus"
    assert status_json["closed_at"]


def test_discussion_engine_rejects_duplicate_round_submission(repo_root, tmp_path) -> None:
    _, discussion_dir = _start_discussion(repo_root, tmp_path)

    first = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "partial",
            "--position",
            "First pass.",
        ],
    )
    assert first.returncode == 0, first.stderr

    second = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "agree",
            "--position",
            "Second pass.",
        ],
    )
    assert second.returncode != 0
    assert "already submitted" in second.stderr


def test_discussion_engine_round_context_supports_utf8_content(repo_root, tmp_path) -> None:
    _, discussion_dir = _start_discussion(repo_root, tmp_path, max_rounds=2)

    s1 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "claude-code",
            "--verdict",
            "partial",
            "--position",
            "caf\u00e9 review with unicode",
        ],
    )
    assert s1.returncode == 0, s1.stderr

    s2 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "1",
            "--agent",
            "codex-cli",
            "--verdict",
            "disagree",
            "--position",
            "na\u00efve approach may fail",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    adv = _run_engine(repo_root, ["advance", "--discussion-dir", str(discussion_dir)])
    assert adv.returncode == 0, adv.stderr
    assert json.loads(adv.stdout)["action"] == "advanced"

    context = _run_engine(
        repo_root,
        [
            "round_context",
            "--discussion-dir",
            str(discussion_dir),
            "--round",
            "2",
            "--agent",
            "claude-code",
        ],
    )
    assert context.returncode == 0, context.stderr
    payload = json.loads(context.stdout)
    assert payload["round"] == 2
    prior_positions = payload["prior_rounds"][0]["positions"]
    assert any("caf\u00e9" in p["position"] for p in prior_positions)
    assert any("na\u00efve" in p["position"] for p in prior_positions)
