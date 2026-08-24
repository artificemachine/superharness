"""shux diff <task-id> — preview agent changes for a task before closing.

Shows the git diff of all files touched by the agent for this task.
Works with both normal commits and worktree branches (fanout/swarm).

Usage:
    shux diff <task-id> [--project PATH] [--stat]
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path

import click

import logging

from superharness.engine.state_errors import StateError

logger = logging.getLogger(__name__)


def _find_task(project_dir: Path, task_id: str) -> dict | None:
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao

        conn = get_connection(str(project_dir))
        try:
            init_db(conn)
            row = tasks_dao.get(conn, task_id)
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "id": row.id,
            "title": row.title,
            "owner": row.owner,
            "status": row.status,
        }
    except Exception as e:
        logger.warning("diff.py unexpected error: %s", e, exc_info=True)
        return None


def _git_diff(project_dir: Path, base: str | None, stat_only: bool) -> str:
    """Return diff text against base ref (or HEAD if base is None)."""
    args = ["git", "diff"]
    if stat_only:
        args.append("--stat")
    if base:
        args.extend([base, "HEAD"])
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_dir),
    )
    return result.stdout


def _find_worktree_branch(project_dir: Path, task_id: str) -> str | None:
    """Return the first worktree branch for task_id if it exists."""
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_dir),
    )
    current_branch = None
    for line in result.stdout.splitlines():
        if line.startswith("branch "):
            current_branch = line[7:].strip()
        if line == "" and current_branch:
            current_branch = None
        if current_branch and f"sh-{task_id}" in current_branch:
            return current_branch
    return None


def _context_diff(project_dir: Path, task_id: str) -> str | None:
    """Diff prompt components between a task's last two SDK dispatches.

    Returns a human-readable report string, or None if the context tables
    are unavailable (e.g. schema not migrated yet). When fewer than two
    dispatches have been recorded, returns a "no prior dispatch" message so
    the caller can still fall back to the ordinary git diff below it.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import context_dao

        conn = get_connection(str(project_dir))
        try:
            init_db(conn)
            dispatch_ids = context_dao.last_dispatches(conn, task_id=task_id, n=2)
            if len(dispatch_ids) < 2:
                return (
                    "no prior dispatch to compare — showing git diff below"
                )

            newest_id, previous_id = dispatch_ids[0], dispatch_ids[1]
            newest = {
                component_type: sha256
                for _, component_type, sha256 in context_dao.components_for_dispatch(
                    conn, newest_id
                )
            }
            previous = {
                component_type: sha256
                for _, component_type, sha256 in context_dao.components_for_dispatch(
                    conn, previous_id
                )
            }
        finally:
            conn.close()
    except (StateError, sqlite3.Error, OSError) as e:
        logger.warning("diff.py unexpected error computing context diff: %s", e)
        return None

    types = sorted(set(previous) | set(newest))
    lines = [f"Context diff: dispatch {previous_id} -> dispatch {newest_id}"]
    for component_type in types:
        old_sha = previous.get(component_type)
        new_sha = newest.get(component_type)
        if old_sha is not None and new_sha is not None:
            if old_sha == new_sha:
                lines.append(f"unchanged: {component_type}")
            else:
                lines.append(
                    f"changed: {component_type} {old_sha[:8]}..{new_sha[:8]}"
                )
        elif new_sha is not None:
            lines.append(f"added: {component_type}")
        else:
            lines.append(f"removed: {component_type}")

    return "\n".join(lines)


def _last_merge_base(project_dir: Path, task_id: str) -> str | None:
    """Find the commit on the default branch right before the task started.

    Looks for a commit whose message references the task_id, else falls back
    to the first parent of the most recent merge commit.
    """
    # Look for a commit that created or mentioned the task
    result = subprocess.run(
        ["git", "log", "--oneline", "--all", "--grep", task_id, "-1"],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(project_dir),
    )
    if result.stdout.strip():
        sha = result.stdout.split()[0]
        # Return the parent of that commit as the base
        parent = subprocess.run(
            ["git", "rev-parse", f"{sha}^"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(project_dir),
        )
        if parent.returncode == 0:
            return parent.stdout.strip()
    return None


@click.command(name="diff")
@click.argument("task_id")
@click.option(
    "--project", "project_str", default=None, help="Project directory (default: cwd)."
)
@click.option(
    "--stat", "stat_only", is_flag=True, default=False, help="Show --stat summary only."
)
@click.option(
    "--base",
    "base_ref",
    default=None,
    help="Compare against this git ref (default: auto-detect).",
)
@click.option(
    "--context",
    "show_context",
    is_flag=True,
    default=False,
    help="Diff prompt components between the last two dispatches.",
)
def cmd_diff(task_id, project_str, stat_only, base_ref, show_context):
    """Preview agent changes for a task before closing.

    \b
    shux diff task-001              # diff for task-001 vs auto-detected base
    shux diff task-001 --stat       # stat summary only
    shux diff task-001 --base main  # diff against a specific branch
    shux diff task-001 --context    # diff dispatch prompt components
    """
    project_dir = Path(project_str or os.getcwd()).resolve()

    if show_context:
        context_report = _context_diff(project_dir, task_id)
        if context_report:
            click.echo(context_report)
            click.echo()

    task = _find_task(project_dir, task_id)
    if task is None:
        click.echo(
            f"warning: task '{task_id}' not found in SQLite — showing uncommitted diff",
            err=True,
        )

    if task:
        click.echo(f"task:   {task_id}")
        click.echo(f"title:  {task.get('title', '?')}")
        click.echo(f"owner:  {task.get('owner', '?')}")
        click.echo(f"status: {task.get('status', '?')}")
        click.echo()

    # Determine base ref
    ref = base_ref
    if not ref:
        ref = _last_merge_base(project_dir, task_id)

    diff_text = _git_diff(project_dir, ref, stat_only)

    if not diff_text.strip():
        # Try unstaged + staged combined
        staged = subprocess.run(
            ["git", "diff", "--cached"] + (["--stat"] if stat_only else []),
            capture_output=True,
            text=True,
            check=False,
            cwd=str(project_dir),
        ).stdout
        unstaged = subprocess.run(
            ["git", "diff"] + (["--stat"] if stat_only else []),
            capture_output=True,
            text=True,
            check=False,
            cwd=str(project_dir),
        ).stdout
        diff_text = staged + unstaged

    if not diff_text.strip():
        click.echo("(no changes found — worktree is clean or no base commit detected)")
        if not base_ref:
            click.echo(f"  tip: shux diff {task_id} --base main")
        return

    click.echo(diff_text)
