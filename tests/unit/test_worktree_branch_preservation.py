"""Iteration 4 (F-06 core): a detached dispatch worktree holding new commits is
branched behind ``superharness/dispatch/<task>`` before teardown.

Real git operations on throwaway tmp repositories — no mocking for the happy
paths, because the branch decision IS the subprocess behavior. The chaos case
monkeypatches only the ``git branch`` invocation to prove a failed preservation
is logged and never blocks removal.
"""

import subprocess

from superharness.commands.inbox_dispatch import _branch_detached_worktree_commits


def _git(*args: str, cwd: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    )
    return r.stdout.strip()


def _init_base_repo(base) -> str:
    base.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=str(base))
    _git("config", "user.email", "t@example.com", cwd=str(base))
    _git("config", "user.name", "t", cwd=str(base))
    (base / "seed.txt").write_text("seed\n")
    _git("add", ".", cwd=str(base))
    _git("commit", "-q", "-m", "seed", cwd=str(base))
    return _git("rev-parse", "HEAD", cwd=str(base))


def _add_worktree(base, wt) -> None:
    _git("worktree", "add", "--detach", str(wt), "HEAD", cwd=str(base))


def test_dirty_detached_worktree_is_branched_before_removal(tmp_path):
    base = tmp_path / "proj"
    base_head = _init_base_repo(base)
    wt = tmp_path / "wt"
    _add_worktree(base, wt)
    (wt / "work.txt").write_text("precious\n")
    _git("add", ".", cwd=str(wt))
    _git("commit", "-q", "-m", "precious work", cwd=str(wt))

    branch = _branch_detached_worktree_commits(str(base), str(wt), "task/1")

    assert branch == "superharness/dispatch/task-1"
    branch_head = _git("rev-parse", branch, cwd=str(base))
    wt_head = _git("rev-parse", "HEAD", cwd=str(wt))
    assert branch_head == wt_head
    assert branch_head != base_head


def test_clean_worktree_removal_unchanged(tmp_path):
    base = tmp_path / "proj"
    _init_base_repo(base)
    wt = tmp_path / "wt"
    _add_worktree(base, wt)

    assert _branch_detached_worktree_commits(str(base), str(wt), "task/1") is None
    assert "dispatch" not in _git("branch", "--list", cwd=str(base))


def test_uncommitted_only_worktree_gets_no_branch(tmp_path):
    base = tmp_path / "proj"
    _init_base_repo(base)
    wt = tmp_path / "wt"
    _add_worktree(base, wt)
    (wt / "scratch.txt").write_text("uncommitted\n")

    assert _branch_detached_worktree_commits(str(base), str(wt), "task/1") is None


def test_branch_failure_returns_none_and_does_not_raise(tmp_path, monkeypatch):
    base = tmp_path / "proj"
    _init_base_repo(base)
    wt = tmp_path / "wt"
    _add_worktree(base, wt)
    (wt / "work.txt").write_text("precious\n")
    _git("add", ".", cwd=str(wt))
    _git("commit", "-q", "-m", "precious work", cwd=str(wt))

    real_run = subprocess.run

    def failing_branch(*args, **kwargs):
        if args and args[0] and "branch" in args[0]:
            raise OSError("disk on fire")
        return real_run(*args, **kwargs)

    monkeypatch.setattr(
        "superharness.commands.inbox_dispatch.subprocess.run", failing_branch
    )
    assert _branch_detached_worktree_commits(str(base), str(wt), "task/1") is None
