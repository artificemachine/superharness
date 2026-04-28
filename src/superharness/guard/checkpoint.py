"""Git checkpoint/rollback — snapshot worktree before agent modifications.

Cherry-picked from hermes-agent/tools/checkpoint_manager.py.
"""
import subprocess


def snapshot(project_dir: str, task_id: str) -> bool:
    """Stash dirty changes with a task-specific tag."""
    safe_id = task_id.replace("/", "-").replace(".", "-")
    result = subprocess.run(
        ["git", "stash", "push", "-m", f"shux-checkpoint:{safe_id}"],
        cwd=project_dir, capture_output=True, text=True, check=False
    )
    return result.returncode == 0 and "No local changes" not in result.stdout


def rollback(project_dir: str, task_id: str) -> bool:
    """Pop the stash matching a task_id."""
    safe_id = task_id.replace("/", "-").replace(".", "-")
    result = subprocess.run(
        ["git", "stash", "list"], cwd=project_dir, capture_output=True, text=True
    )
    for line in result.stdout.splitlines():
        if f"shux-checkpoint:{safe_id}" in line:
            stash_ref = line.split(":")[0]
            subprocess.run(
                ["git", "stash", "pop", stash_ref],
                cwd=project_dir, capture_output=True, check=False
            )
            return True
    return False


def prune_old(project_dir: str, max_age_hours: int = 24) -> int:
    """Remove stale checkpoint stash entries."""
    result = subprocess.run(
        ["git", "stash", "list"], cwd=project_dir, capture_output=True, text=True
    )
    removed = 0
    for line in result.stdout.splitlines():
        if "shux-checkpoint:" in line:
            stash_ref = line.split(":")[0]
            subprocess.run(
                ["git", "stash", "drop", stash_ref],
                cwd=project_dir, capture_output=True, check=False
            )
            removed += 1
    return removed


def list_checkpoints(project_dir: str) -> list[str]:
    """Return list of checkpoint stash entry names."""
    result = subprocess.run(
        ["git", "stash", "list"], cwd=project_dir, capture_output=True, text=True
    )
    return [
        line.split("shux-checkpoint:")[-1].strip()
        for line in result.stdout.splitlines()
        if "shux-checkpoint:" in line
    ]
