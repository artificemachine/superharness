from __future__ import annotations

import json
from pathlib import Path

from tests.helpers import run_bash, run_cmd


def _run_engine(repo_root: Path, args: list[str]):
    return run_cmd(["ruby", str(repo_root / "engine" / "discussion.rb")] + args, cwd=repo_root)


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj-discussion-dispatch"
    harness = project / ".superharness"
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused",
                "",
            ]
        )
        + "\n"
    )
    return project


def _start_discussion(repo_root: Path, project: Path, *, max_rounds: int = 2) -> Path:
    started = _run_engine(
        repo_root,
        [
            "start",
            "--discussions-dir",
            str(project / ".superharness" / "discussions"),
            "--topic",
            "Dispatcher test discussion",
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
    return Path(json.loads(started.stdout)["discussion_dir"])


def test_discussion_dispatch_advances_and_enqueues_next_round(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    discussion_dir = _start_discussion(repo_root, project, max_rounds=2)

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
            "Need changes.",
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
            "Not ready.",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    dispatch = run_bash(repo_root / "scripts" / "discussion-dispatch.sh", cwd=repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "advanced to round 2" in dispatch.stdout
    assert "Enqueued round 2 for claude-code" in dispatch.stdout
    assert "Enqueued round 2 for codex-cli" in dispatch.stdout

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "active"
    assert status_json["current_round"] == 2

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert inbox_text.count("task: " + status_json["id"] + "/round-2") == 2


def test_discussion_dispatch_reenqueues_only_missing_pending_agents(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    discussion_dir = _start_discussion(repo_root, project, max_rounds=3)
    discussion_id = discussion_dir.name
    inbox_file = project / ".superharness" / "inbox.yaml"

    inbox_file.write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale|paused",
                "",
                "- id: existing-claude-r1",
                "  to: claude-code",
                f"  task: {discussion_id}/round-1",
                f"  project: {project}",
                "  status: pending",
                "  priority: 1",
                "  retry_count: 0",
                "  max_retries: 3",
                "  created_at: 2026-03-12T00:00:00Z",
            ]
        )
        + "\n"
    )

    dispatch = run_bash(repo_root / "scripts" / "discussion-dispatch.sh", cwd=repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "Enqueued round 1 for codex-cli" in dispatch.stdout
    assert "Enqueued round 1 for claude-code" not in dispatch.stdout

    inbox_text = inbox_file.read_text()
    assert inbox_text.count(f"task: {discussion_id}/round-1") == 2
    assert inbox_text.count("to: claude-code") == 1
    assert inbox_text.count("to: codex-cli") == 1


def test_discussion_dispatch_closes_max_rounds_without_enqueuing_next_round(repo_root, tmp_path) -> None:
    project = _setup_project(tmp_path)
    discussion_dir = _start_discussion(repo_root, project, max_rounds=1)
    discussion_id = discussion_dir.name

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
            "Looks fine.",
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
            "Needs rework.",
        ],
    )
    assert s2.returncode == 0, s2.stderr

    dispatch = run_bash(repo_root / "scripts" / "discussion-dispatch.sh", cwd=repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "closed (reason=max_rounds_reached, round=1)" in dispatch.stdout

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "no_consensus"

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert f"task: {discussion_id}/round-2" not in inbox_text
