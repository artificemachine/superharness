from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, run_cmd
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_discuss_py(cwd, args: list[str] | None = None):
    """Run discuss Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.discuss"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_dispatch_py(cwd, args: list[str] | None = None):
    """Run discussion_dispatch Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.discussion_dispatch"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_engine(repo_root: Path, args: list[str]):
    import sys
    return run_cmd([sys.executable, "-m", "superharness.engine.discussion"] + args, cwd=repo_root)


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

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
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

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
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

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert "closed (reason=max_rounds_reached, round=1)" in dispatch.stdout

    status = _run_engine(repo_root, ["status", "--discussion-dir", str(discussion_dir)])
    assert status.returncode == 0, status.stderr
    status_json = json.loads(status.stdout)
    assert status_json["status"] == "no_consensus"

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert f"task: {discussion_id}/round-2" not in inbox_text


def _setup_project_with_contract(tmp_path: Path, owners: list[str] | None = None) -> Path:
    """Create a project with contract containing tasks for given owners."""
    if owners is None:
        owners = ["claude-code", "codex-cli"]
    project = tmp_path / "proj-discuss-start"
    harness = project / ".superharness"
    (harness / "discussions").mkdir(parents=True, exist_ok=True)
    (harness / "inbox.yaml").write_text("# inbox\n")
    tasks = []
    for i, owner in enumerate(owners):
        tasks.append(f"  - id: task-{i}\n    owner: {owner}\n    status: todo\n    project_path: \"{project}\"")
    contract = "id: test\ntasks:\n" + "\n".join(tasks) + "\n"
    (harness / "contract.yaml").write_text(contract)
    return project


def test_discuss_start_creates_contract_task_and_enqueues(repo_root, tmp_path) -> None:
    """discuss start creates a contract task for round-1 and enqueues both agents."""
    project = _setup_project_with_contract(tmp_path)

    result = _run_discuss_py(
        repo_root,
        args=["start", "--project", str(project), "--topic", "Test topic", "--max-rounds", "2"],
    )
    assert result.returncode == 0, result.stderr
    assert "Discussion started:" in result.stdout
    assert "Enqueued round 1 for claude-code" in result.stdout
    assert "Enqueued round 1 for codex-cli" in result.stdout

    # Verify contract task was created
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "/round-1" in contract_text
    assert "status: in_progress" in contract_text

    # Both agents enqueued
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "to: claude-code" in inbox_text
    assert "to: codex-cli" in inbox_text


def test_discuss_start_rejects_single_owner(repo_root, tmp_path) -> None:
    """discuss start requires at least 2 distinct owners in the contract."""
    project = _setup_project_with_contract(tmp_path, owners=["codex-cli"])

    result = _run_discuss_py(
        repo_root,
        args=["start", "--project", str(project), "--topic", "Should fail"],
    )
    assert result.returncode == 2
    assert "at least 2 distinct task owners" in result.stderr


def test_discuss_start_rejects_no_owners(repo_root, tmp_path) -> None:
    """discuss start fails when contract has no tasks."""
    project = _setup_project_with_contract(tmp_path, owners=[])

    result = _run_discuss_py(
        repo_root,
        args=["start", "--project", str(project), "--topic", "Should fail"],
    )
    assert result.returncode == 2
    assert "at least 2 distinct task owners" in result.stderr


def test_discuss_start_exclude_owner(repo_root, tmp_path) -> None:
    """discuss start --exclude removes an owner from participants."""
    project = _setup_project_with_contract(tmp_path, owners=["claude-code", "codex-cli", "gemini-cli"])

    result = _run_discuss_py(
        repo_root,
        args=[
            "start", "--project", str(project), "--topic", "Exclude test",
            "--exclude", "codex-cli", "--max-rounds", "2",
        ],
    )
    assert result.returncode == 0, result.stderr
    assert "Discussion started:" in result.stdout
    assert "Participants: claude-code gemini-cli" in result.stdout
    assert "Enqueued round 1 for claude-code" in result.stdout
    assert "Enqueued round 1 for gemini-cli" in result.stdout
    assert "codex-cli" not in result.stdout.split("Participants:")[1]

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "to: claude-code" in inbox_text
    assert "to: gemini-cli" in inbox_text
    assert "to: codex-cli" not in inbox_text


def test_discuss_start_exclude_too_many_rejects(repo_root, tmp_path) -> None:
    """discuss start --exclude fails if fewer than 2 owners remain."""
    project = _setup_project_with_contract(tmp_path, owners=["claude-code", "codex-cli"])

    result = _run_discuss_py(
        repo_root,
        args=[
            "start", "--project", str(project), "--topic", "Should fail",
            "--exclude", "codex-cli",
        ],
    )
    assert result.returncode == 2
    assert "at least 2 distinct task owners" in result.stderr
    assert "Excluded: codex-cli" in result.stderr
