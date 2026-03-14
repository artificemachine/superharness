from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT, run_bash, run_cmd


def _run_engine(repo_root: Path, args: list[str]):
    return run_cmd([sys.executable, "-m", "superharness.engine.discussion"] + args, cwd=repo_root)


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


def _extract_discussion_id(stdout: str) -> str:
    m = re.search(r"Discussion started:\s*(discuss-[A-Za-z0-9T:-]+-[0-9]+-[0-9]+)", stdout)
    assert m, stdout
    return m.group(1)


def test_discussion_cli_lifecycle_to_consensus(repo_root, tmp_path) -> None:
    project = tmp_path / "proj-discuss-lifecycle"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
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
    (harness / "contract.yaml").write_text(
        "id: c1\ntasks:\n"
        "  - id: t-claude\n    owner: claude-code\n    status: todo\n"
        f'    project_path: "{project}"\n'
        "  - id: t-codex\n    owner: codex-cli\n    status: todo\n"
        f'    project_path: "{project}"\n'
    )

    started = _run_discuss_py(
        repo_root,
        args=[
            "start",
            "--project", str(project),
            "--topic", "Integration lifecycle check",
            "--max-rounds", "2",
        ],
    )
    assert started.returncode == 0, started.stderr
    discussion_id = _extract_discussion_id(started.stdout)
    discussion_dir = harness / "discussions" / discussion_id
    assert discussion_dir.exists()

    sub1 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir", str(discussion_dir),
            "--round", "1",
            "--agent", "claude-code",
            "--verdict", "agree",
            "--position", "Approved.",
        ],
    )
    assert sub1.returncode == 0, sub1.stderr

    sub2 = _run_engine(
        repo_root,
        [
            "submit_round",
            "--discussion-dir", str(discussion_dir),
            "--round", "1",
            "--agent", "codex-cli",
            "--verdict", "agree",
            "--position", "Approved as well.",
        ],
    )
    assert sub2.returncode == 0, sub2.stderr

    dispatch = _run_dispatch_py(repo_root, args=["--project", str(project)])
    assert dispatch.returncode == 0, dispatch.stderr
    assert f"Discussion {discussion_id}: closed (reason=consensus, round=1)" in dispatch.stdout

    rounds = _run_discuss_py(
        repo_root,
        args=["rounds", "--project", str(project), "--id", discussion_id],
    )
    assert rounds.returncode == 0, rounds.stderr
    assert "Status: consensus" in rounds.stdout

    listing = _run_discuss_py(
        repo_root,
        args=["list", "--project", str(project)],
    )
    assert listing.returncode == 0, listing.stderr
    assert discussion_id in listing.stdout
    assert "status=consensus" in listing.stdout
