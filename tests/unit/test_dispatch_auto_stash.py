"""Tests for dispatch worktree isolation — agent runs in clean worktree when main is dirty."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import pytest


def _init_git_project(tmp_path: Path) -> Path:
    """Create a git repo with one commit and a .superharness dir."""
    project = tmp_path / "proj"
    project.mkdir()
    env = {**os.environ, "ALLOW_MAIN_COMMIT": "1", "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", "init", str(project)], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(project), "config", "user.email", "test@test.com"], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(project), "config", "user.name", "test"], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(project), "config", "core.hooksPath", "/dev/null"], capture_output=True, check=True, env=env)
    (project / "file.txt").write_text("initial")
    subprocess.run(["git", "-C", str(project), "add", "file.txt"], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "init"], capture_output=True, text=True, check=True, env=env)
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("id: test\ntasks: []\n")
    (project / ".gitignore").write_text(".superharness/\n")
    subprocess.run(["git", "-C", str(project), "add", ".gitignore"], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(project), "commit", "-m", "add gitignore"], capture_output=True, check=True, env=env)
    seed_sqlite_from_yaml(project)
    return project


def _dirty_worktree(project: Path) -> None:
    """Make the worktree dirty with an unstaged change."""
    (project / "file.txt").write_text("dirty")


def _is_dirty(project: Path) -> bool:
    r = subprocess.run(
        ["git", "-C", str(project), "status", "--porcelain"],
        capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


# ── Worktree add/remove ──


def test_worktree_add_creates_clean_checkout(tmp_path):
    """_git_worktree_add creates a clean worktree even when main is dirty."""
    from superharness.commands.inbox_dispatch import _git_worktree_add

    project = _init_git_project(tmp_path)
    _dirty_worktree(project)
    assert _is_dirty(project)

    wt = _git_worktree_add(str(project), "test-task")
    assert wt is not None
    assert os.path.isdir(wt)
    # Worktree should have the committed file with original content
    assert (Path(wt) / "file.txt").read_text() == "initial"
    # Main worktree should still be dirty
    assert _is_dirty(project)


def test_worktree_add_symlinks_superharness(tmp_path):
    """_git_worktree_add symlinks .superharness/ into the worktree."""
    from superharness.commands.inbox_dispatch import _git_worktree_add

    project = _init_git_project(tmp_path)

    wt = _git_worktree_add(str(project), "test-task")
    assert wt is not None
    wt_harness = Path(wt) / ".superharness"
    assert wt_harness.is_symlink()
    assert wt_harness.resolve() == (project / ".superharness").resolve()
    # Contract should be readable through symlink
    assert (wt_harness / "contract.yaml").exists()


def test_worktree_add_returns_none_for_non_git(tmp_path):
    """_git_worktree_add returns None for non-git directories."""
    from superharness.commands.inbox_dispatch import _git_worktree_add

    non_git = tmp_path / "not-a-repo"
    non_git.mkdir()
    wt = _git_worktree_add(str(non_git), "test-task")
    assert wt is None


def test_worktree_remove_cleans_up(tmp_path):
    """_git_worktree_remove deletes the worktree directory."""
    from superharness.commands.inbox_dispatch import _git_worktree_add, _git_worktree_remove

    project = _init_git_project(tmp_path)
    wt = _git_worktree_add(str(project), "test-task")
    assert wt is not None
    assert os.path.isdir(wt)

    ok = _git_worktree_remove(str(project), wt)
    assert ok
    assert not os.path.isdir(wt)


def test_worktree_remove_preserves_original_superharness(tmp_path):
    """_git_worktree_remove does not delete the original .superharness/ dir."""
    from superharness.commands.inbox_dispatch import _git_worktree_add, _git_worktree_remove

    project = _init_git_project(tmp_path)
    wt = _git_worktree_add(str(project), "test-task")
    _git_worktree_remove(str(project), wt)

    # Original .superharness must still exist
    assert (project / ".superharness").is_dir()
    assert (project / ".superharness" / "contract.yaml").exists()


def test_worktree_main_stays_dirty(tmp_path):
    """Main worktree stays dirty throughout worktree lifecycle."""
    from superharness.commands.inbox_dispatch import _git_worktree_add, _git_worktree_remove

    project = _init_git_project(tmp_path)
    _dirty_worktree(project)

    wt = _git_worktree_add(str(project), "test-task")
    assert _is_dirty(project)  # still dirty during dispatch

    _git_worktree_remove(str(project), wt)
    assert _is_dirty(project)  # still dirty after cleanup
    assert (project / "file.txt").read_text() == "dirty"  # changes preserved
