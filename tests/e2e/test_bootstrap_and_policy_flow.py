from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.helpers import REPO_ROOT, copy_from_repo, parse_json_output, run_bash, run_cmd, shell_guard_list
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_init_py(cwd, args: list[str] | None = None):
    """Run init_project Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.init_project"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_discuss_py(cwd, args: list[str] | None = None):
    """Run discuss Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.commands.discuss"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def test_bootstrap_and_hook_install_flow(repo_root, tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    init_res = _run_init_py(project, args=["Demo", "Python", "active"])
    assert init_res.returncode == 0, init_res.stderr

    assert (project / ".superharness/contract.yaml").exists()
    assert (project / "CLAUDE.md").exists()
    assert (project / "AGENTS.md").exists()

    # Install git hooks into a temp git repo that has the required scripts/hook files.
    required = (
        shell_guard_list(REPO_ROOT, "--list-entrypoints")
        + shell_guard_list(REPO_ROOT, "--list-hooks")
        + [
            "protocol/templates/identity-core.md",
            "superharness",
        ]
    )
    for rel in sorted(set(required)):
        copy_from_repo(rel, project)

    run_cmd(["git", "init"], cwd=project)
    run_cmd(["git", "config", "user.email", "test@example.com"], cwd=project)
    run_cmd(["git", "config", "user.name", "tester"], cwd=project)
    run_cmd(["git", "add", "."], cwd=project)

    isolated_home = project / "home"
    isolated_home.mkdir()
    install_hooks = run_bash(
        project / "src/superharness/scripts/install-git-hooks.sh",
        cwd=project,
        env={"HOME": str(isolated_home)},
    )
    assert install_hooks.returncode == 0

    hooks_path = run_cmd(["git", "config", "--get", "core.hooksPath"], cwd=project)
    assert hooks_path.stdout.strip() == ".githooks"


def test_policy_enforcement_block_and_warn(repo_root, tmp_path) -> None:
    branch_guard = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    scope_guard = repo_root / "adapters/claude-code/hooks/scope-guard.sh"

    block_payload = json.dumps({"tool_input": {"command": "git push origin main"}})
    block_res = run_bash(branch_guard, cwd=tmp_path, stdin=block_payload)
    block = parse_json_output(block_res.stdout)
    # branch-guard uses new Claude Code PreToolUse schema
    assert block["hookSpecificOutput"]["permissionDecision"] == "deny"

    warn_payload = json.dumps({"tool_input": {"file_path": "/etc/passwd"}})
    warn_res = run_bash(scope_guard, cwd=tmp_path, stdin=warn_payload)
    warn = parse_json_output(warn_res.stdout)
    assert warn["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_bootstrap_discuss_start_enqueues_round_one_for_both_agents(repo_root, tmp_path) -> None:
    project = tmp_path / "project_discuss"
    project.mkdir()

    init_res = _run_init_py(project, args=["Demo", "Python", "active"])
    assert init_res.returncode == 0, init_res.stderr

    # Add tasks for both owners (required for discussion start)
    task_script = repo_root / "src" / "superharness" / "scripts" / "task.sh"
    for agent in ("claude-code", "codex-cli"):
        t = run_bash(task_script, cwd=repo_root, args=[
            "create", "--project", str(project),
            "--id", f"e2e-{agent}", "--title", f"E2E task for {agent}",
            "--owner", agent, "--status", "todo",
        ])
        assert t.returncode == 0, t.stderr

    start_res = _run_discuss_py(
        repo_root,
        args=[
            "start",
            "--project", str(project),
            "--topic", "E2E test: dual-agent round enqueue",
            "--max-rounds", "2",
        ],
    )
    assert start_res.returncode == 0, start_res.stderr
    assert "Discussion started:" in start_res.stdout
    assert "Enqueued round 1 for claude-code:" in start_res.stdout
    assert "Enqueued round 1 for codex-cli:" in start_res.stdout

    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "task: discuss-" in inbox_text
    assert "/round-1" in inbox_text
    assert "to: claude-code" in inbox_text
    assert "to: codex-cli" in inbox_text
    assert "status: pending" in inbox_text
