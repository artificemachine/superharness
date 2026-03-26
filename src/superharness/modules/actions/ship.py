"""Ship module actions — auto-commit and push on task close."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def git_ship(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Auto-commit and optionally push changes on task close.

    Args:
        context: Context dict with task_id, project_dir, event, summary
        settings: Module settings with auto_push flag

    Returns:
        Result dict with success status and message
    """
    project_dir = Path(context.get("project_dir", "."))
    task_id = context.get("task_id", "unknown")
    summary = context.get("summary", f"Completed task {task_id}")

    # Check if we're in a git repository
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=project_dir,
            check=True,
            capture_output=True,
            timeout=5,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        logger.debug(f"Not a git repository or git not available: {e}")
        return {
            "success": False,
            "message": "Not a git repository or git not available",
            "skipped": True,
        }

    # Check for uncommitted changes
    try:
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )

        if not status_result.stdout.strip():
            logger.info("No uncommitted changes, skipping ship")
            return {
                "success": True,
                "message": "Nothing to commit, skipped",
                "skipped": True,
            }

    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to check git status: {e}")
        return {
            "success": False,
            "message": f"Failed to check git status: {e}",
            "error": str(e),
        }

    # Add all changes
    try:
        logger.info(f"Adding all changes for task {task_id}")
        subprocess.run(
            ["git", "add", "-A"],
            cwd=project_dir,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to add changes: {e}")
        return {
            "success": False,
            "message": f"Failed to add changes: {e}",
            "error": str(e),
        }

    # Commit changes
    commit_message = f"{summary}\n\nTask: {task_id}\nAuto-committed by superharness ship module"

    try:
        logger.info(f"Committing changes for task {task_id}")
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            cwd=project_dir,
            check=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to commit changes: {e}")
        return {
            "success": False,
            "message": f"Failed to commit changes: {e}",
            "error": str(e),
        }

    # Optionally push changes
    auto_push = settings.get("auto_push", False)
    if auto_push:
        try:
            logger.info(f"Pushing changes for task {task_id}")
            subprocess.run(
                ["git", "push"],
                cwd=project_dir,
                check=True,
                capture_output=True,
                timeout=30,
            )
            return {
                "success": True,
                "message": f"Changes committed and pushed for task {task_id}",
            }
        except subprocess.CalledProcessError as e:
            logger.warning(f"Failed to push changes (commit succeeded): {e}")
            return {
                "success": True,
                "message": f"Changes committed (push failed: {e})",
                "warning": str(e),
            }
    else:
        logger.info(f"Changes committed for task {task_id} (auto_push disabled)")
        return {
            "success": True,
            "message": f"Changes committed for task {task_id}",
        }
