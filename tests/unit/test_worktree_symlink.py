"""Regression test for the worktree .superharness/ symlink race.

Bug: .superharness/ is tracked in git, so `git worktree add` checks out a
stale copy from HEAD. The symlink-creation code then saw dst_harness
already existed and skipped the symlink. The worktree's .superharness/
diverged from the live source, the lifecycle gate read empty/stale task
status, and every dispatch into a worktree was rejected with
"status is '' for workflow ..."

Fix: _git_worktree_add must replace any pre-existing real dir with a
symlink to the live source.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")
sys.path.insert(0, SRC)


@pytest.fixture
def git_project(tmp_path):
    """Build a tiny git repo with a tracked .superharness/contract.yaml."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "-C", str(project), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "t@e.x"], check=True)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "t"], check=True)
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks:\n  - id: t1\n    status: in_progress\n")
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    env = os.environ.copy()
    env["ALLOW_MAIN_COMMIT"] = "1"
    env["ALLOW_NO_CHANGELOG"] = "1"
    subprocess.run(
        ["git", "-C", str(project), "commit", "-q", "-m", "init", "--no-verify"],
        check=True, env=env,
    )
    return project


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_git_worktree_add_replaces_checked_out_superharness_with_symlink(git_project):
    """When .superharness/ is tracked in git, _git_worktree_add must
    overwrite the checked-out copy with a symlink to the live source."""
    from superharness.commands import inbox_dispatch

    worktree = inbox_dispatch._git_worktree_add(str(git_project), "test-task")
    assert worktree is not None, "worktree creation failed"
    try:
        dst = Path(worktree) / ".superharness"
        assert dst.is_symlink(), (
            f".superharness/ in the worktree is not a symlink. "
            f"It's: {os.lstat(dst)}. The dispatch lifecycle gate will read a "
            f"stale checked-out copy and reject every task."
        )
        assert os.readlink(dst) == str(git_project / ".superharness")
    finally:
        inbox_dispatch._git_worktree_remove(str(git_project), worktree)


def test_get_connection_uses_state_project_env_var(tmp_path):
    """SUPERHARNESS_STATE_PROJECT overrides the project_dir used for XDG hashing.

    Regression: when delegate.py runs from a worktree path, get_connection hashed
    the worktree path and opened an empty database. Setting SUPERHARNESS_STATE_PROJECT
    to the original project path restores the correct hash.
    """
    import os
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    real_project = tmp_path / "real_project"
    real_project.mkdir()
    worktree_dir = tmp_path / "worktree"
    worktree_dir.mkdir()

    # Create a task in the real project database
    conn_real = get_connection(str(real_project))
    init_db(conn_real)
    conn_real.execute(
        "INSERT INTO tasks (id, title, owner, status, workflow, created_at) VALUES (?,?,?,?,?,?)",
        ("task-wt-test", "Worktree test task", "claude-code", "todo", "implementation", "2026-05-19T00:00:00Z"),
    )
    conn_real.commit()
    conn_real.close()

    # Without env var: get_connection from worktree_dir opens a different (empty) DB
    conn_wt = get_connection(str(worktree_dir))
    init_db(conn_wt)
    assert tasks_dao.get(conn_wt, "task-wt-test") is None, (
        "task should NOT be visible from the worktree path without env var"
    )
    conn_wt.close()

    # With env var: get_connection from worktree_dir resolves to real project DB
    old_env = os.environ.get("SUPERHARNESS_STATE_PROJECT")
    try:
        os.environ["SUPERHARNESS_STATE_PROJECT"] = str(real_project)
        conn_via_env = get_connection(str(worktree_dir))
        init_db(conn_via_env)
        task = tasks_dao.get(conn_via_env, "task-wt-test")
        assert task is not None, "task should be visible when SUPERHARNESS_STATE_PROJECT is set"
        assert task.status == "todo"
        conn_via_env.close()
    finally:
        if old_env is None:
            os.environ.pop("SUPERHARNESS_STATE_PROJECT", None)
        else:
            os.environ["SUPERHARNESS_STATE_PROJECT"] = old_env


def test_worktree_symlink_resolves_to_live_source_state(git_project):
    """After symlinking, mutations to the source .superharness/ must be
    visible from inside the worktree (proves it's a symlink, not a copy)."""
    from superharness.commands import inbox_dispatch

    worktree = inbox_dispatch._git_worktree_add(str(git_project), "test-task-2")
    assert worktree is not None
    try:
        # Mutate source contract after worktree creation
        (git_project / ".superharness" / "contract.yaml").write_text(
            "tasks:\n  - id: t1\n    status: done\n"
        )
        # Read via worktree path — must see the new content via symlink
        seen = (Path(worktree) / ".superharness" / "contract.yaml").read_text()
        assert "status: done" in seen, (
            "worktree's .superharness/ does not reflect live source state. "
            f"Got: {seen!r}"
        )
    finally:
        inbox_dispatch._git_worktree_remove(str(git_project), worktree)
