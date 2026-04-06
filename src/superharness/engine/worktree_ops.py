"""Shared git worktree helpers used by parallel_dispatch and swarm."""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field


def sanitize_task_id(task_id: str) -> str:
    """Sanitize task_id for safe use in git branch names and filesystem paths.

    Only allows alphanumeric, hyphens, underscores, and dots.
    Rejects path traversal components.
    """
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '-', task_id)
    if '..' in sanitized or sanitized.startswith('/'):
        sanitized = sanitized.replace('..', '--').lstrip('/')
    return sanitized[:100]


@dataclass
class WorktreeSlot:
    """One parallel dispatch slot."""
    index: int
    branch: str
    worktree_path: str
    project_dir: str = ""
    status: str = "pending"  # pending, running, done, failed
    result: dict = field(default_factory=dict)
    error: str = ""
    cost_usd: float = 0.0
    duration_seconds: float = 0.0


def create_worktree(project_dir: str, branch: str, path: str) -> bool:
    """Create a git worktree for isolated agent dispatch."""
    try:
        r = subprocess.run(
            ["git", "worktree", "add", "-b", branch, path, "HEAD"],
            capture_output=True, text=True, check=False, cwd=project_dir,
        )
        return r.returncode == 0
    except (OSError, FileNotFoundError):
        return False


def remove_worktree(project_dir: str, path: str, branch: str) -> None:
    """Remove a git worktree and its branch."""
    subprocess.run(
        ["git", "worktree", "remove", "--force", path],
        capture_output=True, text=True, check=False, cwd=project_dir,
    )
    subprocess.run(
        ["git", "branch", "-D", branch],
        capture_output=True, text=True, check=False, cwd=project_dir,
    )


def copy_superharness_state(src_dir: str, dst_dir: str) -> None:
    """Symlink .superharness/ state into worktree so the agent has context."""
    src = os.path.join(src_dir, ".superharness")
    dst = os.path.join(dst_dir, ".superharness")
    if not os.path.isdir(src):
        return
    if os.path.exists(dst):
        return
    os.symlink(src, dst)
