"""Smoke tests — worktree dispatch state isolation (v1.62.1).

Black-box CLI-level tests verifying that SUPERHARNESS_STATE_PROJECT allows
`shux delegate --print-only` to find a task when the --project arg points
at an ephemeral worktree path instead of the real project directory.

These complement the E2E component tests in
tests/e2e/test_worktree_dispatch_state_isolation.py by exercising the full
CLI entry point.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")


def _shux(*args: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run shux with the dev src on PYTHONPATH."""
    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = SRC
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "superharness.cli", *args],
        capture_output=True, text=True, env=base_env, cwd=cwd,
    )


def _seed_project(project_dir: Path) -> str:
    """Init project, seed a todo task, return task_id."""
    import uuid
    from superharness.engine.db import get_connection, init_db

    sh = project_dir / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "handoffs").mkdir(exist_ok=True)
    (sh / "discussions").mkdir(exist_ok=True)
    (sh / "profile.yaml").write_text(
        "project_name: smoke-test\n"
        "created: 2026-01-01\n"
        "primary_agent: claude-code\n"
        "autonomy: ai_driven\n"
        "require_tdd: false\n"
        "state_backend: sqlite_only\n"
    )

    task_id = f"smoke-{uuid.uuid4().hex[:6]}"
    conn = get_connection(str(project_dir))
    try:
        init_db(conn)
        conn.execute(
            "INSERT INTO tasks (id, title, owner, status, workflow, created_at, "
            "acceptance_criteria) VALUES (?,?,?,?,?,?,?)",
            (task_id, "Smoke test task", "claude-code", "todo",
             "implementation", "2026-05-19T00:00:00Z", '["criteria A"]'),
        )
        conn.commit()
    finally:
        conn.close()

    return task_id


# ---------------------------------------------------------------------------
# Smoke-1: delegate --print-only works when called with real project path
# ---------------------------------------------------------------------------

def test_delegate_print_only_real_project(tmp_path: Path) -> None:
    """Baseline: delegate --print-only on the real project path must succeed."""
    project = tmp_path / "real"
    project.mkdir()
    task_id = _seed_project(project)

    result = _shux(
        "delegate", task_id,
        "--project", str(project),
        "--print-only",
        "--plan-only",
    )
    assert result.returncode == 0, (
        f"delegate --print-only failed on real project path.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Smoke-2: delegate --print-only fails without env var from worktree path
# ---------------------------------------------------------------------------

def test_delegate_print_only_worktree_without_env_var_fails(tmp_path: Path) -> None:
    """Regression guard: without SUPERHARNESS_STATE_PROJECT, passing the
    worktree path must cause Gate 5 to fire (status=''), returning exit 2."""
    project = tmp_path / "real"
    project.mkdir()
    task_id = _seed_project(project)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".superharness").mkdir()  # empty — no state.db

    env = {"SUPERHARNESS_STATE_PROJECT": ""}  # explicitly unset

    result = _shux(
        "delegate", task_id,
        "--project", str(worktree),
        "--print-only",
        "--plan-only",
        env=env,
    )
    # Should fail: worktree not initialized (no DB) → exit 1 before Gate 5
    assert result.returncode != 0, (
        "Expected delegate to fail when called with worktree path and no "
        f"SUPERHARNESS_STATE_PROJECT. stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Smoke-3: delegate --print-only succeeds with env var pointing to real project
# ---------------------------------------------------------------------------

def test_delegate_print_only_worktree_with_env_var_succeeds(tmp_path: Path) -> None:
    """Core fix verification: when SUPERHARNESS_STATE_PROJECT points at the
    real project, delegate --print-only called with the worktree path must
    find the task and succeed."""
    project = tmp_path / "real"
    project.mkdir()
    task_id = _seed_project(project)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    wt_sh = worktree / ".superharness"
    wt_sh.mkdir()
    (wt_sh / "handoffs").mkdir()
    (wt_sh / "discussions").mkdir()

    result = _shux(
        "delegate", task_id,
        "--project", str(worktree),
        "--print-only",
        "--plan-only",
        env={"SUPERHARNESS_STATE_PROJECT": str(project)},
    )
    assert result.returncode == 0, (
        f"delegate --print-only must succeed when SUPERHARNESS_STATE_PROJECT "
        f"points at the real project.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ---------------------------------------------------------------------------
# Smoke-4: env var with wrong path still fails (not a blanket bypass)
# ---------------------------------------------------------------------------

def test_delegate_print_only_wrong_env_var_fails(tmp_path: Path) -> None:
    """SUPERHARNESS_STATE_PROJECT pointing at the wrong project must still
    fail — it is not a blanket gate bypass."""
    project = tmp_path / "real"
    project.mkdir()
    task_id = _seed_project(project)

    wrong_project = tmp_path / "wrong"
    wrong_project.mkdir()
    (wrong_project / ".superharness").mkdir()  # different DB, task not there

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".superharness").mkdir()

    result = _shux(
        "delegate", task_id,
        "--project", str(worktree),
        "--print-only",
        "--plan-only",
        env={"SUPERHARNESS_STATE_PROJECT": str(wrong_project)},
    )
    assert result.returncode != 0, (
        "delegate must fail when SUPERHARNESS_STATE_PROJECT points at a "
        f"project that doesn't contain the task.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
