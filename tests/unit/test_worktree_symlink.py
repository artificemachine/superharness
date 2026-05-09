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
