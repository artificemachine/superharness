from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.helpers import REPO_ROOT, copy_from_repo, parse_json_output, run_bash, run_cmd, shell_guard_list
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_init_py(cwd, args: list[str] | None = None, extra_env: dict | None = None):
    """Run init_project Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", "superharness.commands.init_project"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _run_discuss_py(cwd, args: list[str] | None = None, extra_env: dict | None = None):
    """Run discuss Python module."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", "superharness.commands.discuss"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def test_bootstrap_and_hook_install_flow(repo_root, tmp_path) -> None:
    from superharness.utils.paths import resolve_xdg_state_db_path

    project = tmp_path / "project"
    project.mkdir()
    state_dir = str(tmp_path / "sh_state")

    init_res = _run_init_py(project, args=["Demo", "Python", "active"],
                            extra_env={"SUPERHARNESS_STATE_DIR": state_dir})
    assert init_res.returncode == 0, init_res.stderr

    # Post-migration: state lives in XDG state db, not inside .superharness/.
    old_env = os.environ.get("SUPERHARNESS_STATE_DIR")
    os.environ["SUPERHARNESS_STATE_DIR"] = state_dir
    try:
        xdg_db = resolve_xdg_state_db_path(str(project))
    finally:
        if old_env is None:
            os.environ.pop("SUPERHARNESS_STATE_DIR", None)
        else:
            os.environ["SUPERHARNESS_STATE_DIR"] = old_env
    assert os.path.isfile(xdg_db), f"XDG state.db not found at {xdg_db}"
    assert not (project / ".superharness" / "state.sqlite3").exists(), \
        "legacy state.sqlite3 must not exist after init"
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
    import sqlite3 as _sql
    from superharness.utils.paths import resolve_xdg_state_db_path

    project = tmp_path / "project_discuss"
    project.mkdir()
    state_dir = str(tmp_path / "sh_state_discuss")

    init_res = _run_init_py(project, args=["Demo", "Python", "active"],
                            extra_env={"SUPERHARNESS_STATE_DIR": state_dir})
    assert init_res.returncode == 0, init_res.stderr

    # Add tasks for both owners (required for discussion start)
    task_script = repo_root / "src" / "superharness" / "scripts" / "task.sh"
    for agent in ("claude-code", "codex-cli"):
        t = run_bash(task_script, cwd=repo_root, args=[
            "create", "--project", str(project),
            "--id", f"e2e-{agent}", "--title", f"E2E task for {agent}",
            "--owner", agent, "--status", "todo",
        ], env={"SUPERHARNESS_STATE_DIR": state_dir})
        assert t.returncode == 0, t.stderr

    start_res = _run_discuss_py(
        repo_root,
        args=[
            "start",
            "--project", str(project),
            "--topic", "E2E test: dual-agent round enqueue",
            "--max-rounds", "2",
        ],
        extra_env={"SUPERHARNESS_STATE_DIR": state_dir},
    )
    assert start_res.returncode == 0, start_res.stderr
    assert "Discussion started:" in start_res.stdout
    assert "Enqueued round 1 for claude-code:" in start_res.stdout
    assert "Enqueued round 1 for codex-cli:" in start_res.stdout

    # Inbox is SQLite-backed at the XDG path post-migration.
    old_env = os.environ.get("SUPERHARNESS_STATE_DIR")
    os.environ["SUPERHARNESS_STATE_DIR"] = state_dir
    try:
        xdg_db = resolve_xdg_state_db_path(str(project))
    finally:
        if old_env is None:
            os.environ.pop("SUPERHARNESS_STATE_DIR", None)
        else:
            os.environ["SUPERHARNESS_STATE_DIR"] = old_env

    db = _sql.connect(xdg_db)
    rows = db.execute(
        "SELECT task_id, target_agent, status FROM inbox "
        "WHERE task_id LIKE 'discuss-%/round-1'"
    ).fetchall()
    db.close()
    assert rows, f"expected a discuss-*/round-1 row in inbox, got {rows}"
    targets = {r[1] for r in rows}
    statuses = {r[2] for r in rows}
    assert "claude-code" in targets
    assert "codex-cli" in targets
    assert "pending" in statuses
