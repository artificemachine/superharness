"""Local commit of a finished task's dispatch worktree, on a dedicated branch.

Dispatch worktrees are created detached (`git worktree add --detach`) and
removed when the task closes, so a commit made there would become unreachable.
The work is therefore committed on `superharness/task/<task_id>`, which outlives
the worktree. Nothing is pushed, and protected branches are never committed to.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

PROTECTED_BRANCHES = frozenset({"main", "master"})
BRANCH_PREFIX = "superharness/task/"
# The worktree's .superharness is a symlink to the project's state; never commit it.
_EXCLUDE = ":(exclude).superharness"
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_GIT_TIMEOUT = 60

Outcome = Literal["committed", "branched", "clean", "skipped", "failed"]


@dataclass(frozen=True)
class CommitResult:
    outcome: Outcome
    message: str
    branch: str = ""
    sha: str = ""

    @property
    def preserve_worktree(self) -> bool:
        """True when removing the worktree could lose uncommitted work."""
        return self.outcome in ("skipped", "failed")


def _git(wt_path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", wt_path, *args],
        capture_output=True,
        text=True,
        timeout=_GIT_TIMEOUT,
        check=False,
    )


def _head_is_on_a_branch(wt_path: str) -> bool:
    """True when some local branch already contains HEAD."""
    r = _git(wt_path, "for-each-ref", "--contains", "HEAD", "refs/heads", "--count=1")
    return r.returncode == 0 and bool(r.stdout.strip())


def has_unsaved_work(wt_path: str) -> bool:
    """True when removing the worktree would lose work, or git cannot say.

    Unsaved work is either uncommitted changes, or commits made on a detached
    HEAD that no local branch contains (they would become unreachable). Files
    that git ignores (caches, build output) are disposable: they do not count,
    are never committed and are not kept.
    """
    try:
        status = _git(wt_path, "status", "--porcelain", "--", ".", _EXCLUDE)
        if status.returncode != 0 or status.stdout.strip():
            return True
        detached = _git(wt_path, "symbolic-ref", "--short", "-q", "HEAD").returncode != 0
        return detached and not _head_is_on_a_branch(wt_path)
    except (OSError, subprocess.SubprocessError):
        return True


def commit_task_worktree(wt_path: str, task_id: str, summary: str) -> CommitResult:
    """Commit the worktree's changes on a task branch. Never raises, never pushes."""
    parts = task_id.split("/")
    if ".." in task_id or not all(
        _TOKEN_RE.match(p) and not p.endswith(".lock") for p in parts
    ):
        return CommitResult("skipped", f"task id {task_id!r} is not a safe branch name")
    branch = f"{BRANCH_PREFIX}{task_id}"

    try:
        head = _git(wt_path, "symbolic-ref", "--short", "-q", "HEAD")
        current = head.stdout.strip() if head.returncode == 0 else ""
        if current in PROTECTED_BRANCHES:
            return CommitResult(
                "skipped", f"worktree is on protected branch {current!r}", current
            )

        status = _git(wt_path, "status", "--porcelain", "--", ".", _EXCLUDE)
        if status.returncode != 0:
            return CommitResult("failed", f"git status failed: {status.stderr.strip()}")
        dirty = bool(status.stdout.strip())
        detached = not current
        # The commit always lands on the dedicated branch. A detached HEAD gets
        # it, and so does a dirty worktree attached to any other branch: that
        # branch may be shared work, so its ref must never move.
        needs_branch = (detached and (dirty or not _head_is_on_a_branch(wt_path))) or (
            dirty and bool(current) and current != branch
        )

        if not dirty and not needs_branch:
            return CommitResult("clean", "nothing to commit", current)

        if needs_branch:
            sw = _git(wt_path, "switch", "-c", branch)
            if sw.returncode != 0:
                return CommitResult(
                    "failed", f"could not create {branch}: {sw.stderr.strip()}"
                )
            current = branch

        if not dirty:
            sha = _git(wt_path, "rev-parse", "HEAD").stdout.strip()
            return CommitResult(
                "branched", f"kept existing commits on {current}", current, sha
            )

        add = _git(wt_path, "add", "-A", "--", ".", _EXCLUDE)
        if add.returncode != 0:
            return CommitResult("failed", f"git add failed: {add.stderr.strip()}", current)

        message = f"{summary or f'Complete task {task_id}'}\n\nTask: {task_id}"
        commit = _git(wt_path, "commit", "-m", message)
        if commit.returncode != 0:
            detail = (commit.stderr or commit.stdout).strip().splitlines()
            return CommitResult(
                "failed",
                f"git commit failed: {detail[-1] if detail else 'no output'}",
                current,
            )
        sha = _git(wt_path, "rev-parse", "HEAD").stdout.strip()
        return CommitResult("committed", f"committed on {current}", current, sha)
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("commit_task_worktree: %s", e, exc_info=True)
        return CommitResult("failed", f"git unavailable: {e}")
