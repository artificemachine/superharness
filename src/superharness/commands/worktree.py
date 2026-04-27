"""shux worktree — manual worktree management.

    shux worktree list    [--project PATH]
    shux worktree create  <task-id> [--project PATH]
    shux worktree remove  <path>    [--project PATH]
    shux worktree gc                [--project PATH] [--dry-run]
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import click

WORKTREE_BASE = os.path.join(tempfile.gettempdir(), "superharness-worktrees")


def _project(project_str: str | None) -> Path:
    return Path(project_str or os.getcwd()).resolve()


def _git_worktrees(project_dir: Path) -> list[dict]:
    """Return parsed output of `git worktree list --porcelain`."""
    r = subprocess.run(
        ["git", "-C", str(project_dir), "worktree", "list", "--porcelain"],
        capture_output=True, text=True, check=False,
    )
    worktrees = []
    current: dict = {}
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1].strip()[:8]
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].strip()
        elif line == "detached":
            current["branch"] = "(detached)"
        elif line == "bare":
            current["branch"] = "(bare)"
    if current:
        worktrees.append(current)
    return worktrees


@click.group(name="worktree")
def cmd_worktree():
    """Manage git worktrees for isolated agent dispatch."""


@cmd_worktree.command(name="list")
@click.option("--project", "-p", default=None, help="Project directory (default: cwd)")
def worktree_list(project):
    """List active worktrees for this project."""
    project_dir = _project(project)
    worktrees = _git_worktrees(project_dir)
    if not worktrees:
        click.echo("no worktrees found")
        return
    click.echo(f"{'path':<55} {'branch':<30} {'head'}")
    click.echo("-" * 95)
    for wt in worktrees:
        path = wt.get("path", "")
        branch = wt.get("branch", "")
        head = wt.get("head", "")
        linked = " [superharness]" if os.path.exists(os.path.join(path, ".superharness")) else ""
        click.echo(f"{path:<55} {branch:<30} {head}{linked}")


@cmd_worktree.command(name="create")
@click.argument("task_id")
@click.option("--project", "-p", default=None, help="Project directory (default: cwd)")
def worktree_create(task_id, project):
    """Create an isolated worktree for TASK_ID and print its path."""
    project_dir = _project(project)
    if not (project_dir / ".git").exists() and not (project_dir / ".superharness").exists():
        click.echo(f"error: {project_dir} is not a git repo with superharness", err=True)
        sys.exit(1)

    worktree_dir = os.path.join(WORKTREE_BASE, f"{task_id}-{uuid.uuid4().hex[:8]}")
    os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)

    r = subprocess.run(
        ["git", "-C", str(project_dir), "worktree", "add", "--detach", worktree_dir, "HEAD"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        click.echo(f"error: git worktree add failed: {r.stderr.strip()}", err=True)
        sys.exit(1)

    src_harness = str(project_dir / ".superharness")
    dst_harness = os.path.join(worktree_dir, ".superharness")
    if os.path.isdir(src_harness) and not os.path.exists(dst_harness):
        os.symlink(src_harness, dst_harness)

    click.echo(f"created: {worktree_dir}")
    click.echo(f"  cd {worktree_dir}")


@cmd_worktree.command(name="remove")
@click.argument("path")
@click.option("--project", "-p", default=None, help="Project directory (default: cwd)")
def worktree_remove(path, project):
    """Remove a worktree by PATH."""
    project_dir = _project(project)
    dst_harness = os.path.join(path, ".superharness")
    if os.path.islink(dst_harness):
        os.unlink(dst_harness)

    r = subprocess.run(
        ["git", "-C", str(project_dir), "worktree", "remove", "--force", path],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        click.echo(f"error: {r.stderr.strip()}", err=True)
        sys.exit(1)

    subprocess.run(
        ["git", "-C", str(project_dir), "worktree", "prune"],
        capture_output=True, check=False,
    )
    click.echo(f"removed: {path}")


@cmd_worktree.command(name="gc")
@click.option("--project", "-p", default=None, help="Project directory (default: cwd)")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be removed without removing")
def worktree_gc(project, dry_run):
    """Remove orphaned dispatch worktrees."""
    from superharness.commands.worktree_gc import run_worktree_gc
    project_dir = _project(project)
    run_worktree_gc(str(project_dir), dry_run=dry_run)


def main(argv: list[str] | None = None) -> None:
    cmd_worktree(args=argv if argv is not None else sys.argv[1:])


if __name__ == "__main__":
    main()
