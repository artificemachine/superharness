"""Parallel fan-out dispatch — run N agents concurrently on git worktrees.

Each agent gets an isolated worktree branch, runs independently, and results
are collected for merge or voting.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import logging
logger = logging.getLogger(__name__)

from superharness.engine.worktree_ops import (
    WorktreeSlot,
    copy_superharness_state,
    create_worktree,
    remove_worktree,
    sanitize_task_id,
)

# Private aliases kept for any code that imported these directly before
# the shared module was extracted.
_sanitize_task_id = sanitize_task_id
_create_worktree = create_worktree
_remove_worktree = remove_worktree
_copy_superharness_state = copy_superharness_state


@dataclass
class FanoutResult:
    """Aggregated result from parallel dispatch."""
    slots: list[WorktreeSlot]
    total_cost_usd: float = 0.0
    total_duration_seconds: float = 0.0
    merge_conflicts: list[str] = field(default_factory=list)
    winner_index: int | None = None


def _run_sdk_in_worktree(
    slot: WorktreeSlot,
    prompt: str,
    model: str | None,
    max_budget_usd: float | None,
) -> None:
    """Run SDK dispatch in a worktree slot (called from thread)."""
    start = time.time()
    slot.status = "running"
    try:
        from superharness.engine.sdk_runner import SDKRunner
        runner = SDKRunner(
            project_dir=Path(slot.worktree_path),
            model=model,
            max_budget_usd=max_budget_usd,
            warm_start=False,  # Each worktree is independent
        )
        log_dir = Path(slot.worktree_path) / ".superharness" / "launcher-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"parallel-slot-{slot.index}.log"

        result = runner.run(prompt, log_file=log_file)
        slot.result = result
        slot.cost_usd = result.get("cost_usd", 0.0)
        slot.status = "done"
    except Exception as e:
        slot.error = str(e)
        slot.status = "failed"
    slot.duration_seconds = time.time() - start

    # Record failure pattern if slot failed
    if slot.status == "failed" and slot.error and slot.project_dir:
        try:
            from superharness.engine.failure_patterns import record_failure
            record_failure(slot.project_dir, f"parallel-slot-{slot.index}", slot.error)
        except Exception as e:
            logger.warning("parallel_dispatch.py unexpected error: %s", e, exc_info=True)
            pass
    # Record benchmark entry for this slot
    if slot.project_dir:
        try:
            from superharness.engine.benchmark import record_dispatch
            record_dispatch(
                slot.project_dir,
                task_id=f"parallel-slot-{slot.index}",
                agent="parallel-dispatch",
                outcome=slot.status,
                duration_seconds=slot.duration_seconds,
                cost_usd=slot.cost_usd,
                slot_index=slot.index,
            )
        except Exception as e:
            logger.warning("parallel_dispatch.py unexpected error: %s", e, exc_info=True)
            pass
def _collect_diffs(project_dir: str, slots: list[WorktreeSlot]) -> list[dict]:
    """Collect git diffs from each completed worktree slot."""
    diffs = []
    for slot in slots:
        if slot.status != "done":
            continue
        r = subprocess.run(
            ["git", "diff", "HEAD", "--stat"],
            capture_output=True, text=True, check=False,
            cwd=slot.worktree_path,
        )
        diff_detail = subprocess.run(
            ["git", "diff", "HEAD"],
            capture_output=True, text=True, check=False,
            cwd=slot.worktree_path,
        )
        diffs.append({
            "index": slot.index,
            "branch": slot.branch,
            "stat": r.stdout.strip(),
            "diff": diff_detail.stdout[:10000],  # Cap at 10KB
            "cost_usd": slot.cost_usd,
        })
    return diffs


def _try_merge(project_dir: str, branch: str) -> tuple[bool, str]:
    """Try to merge a worktree branch back to HEAD. Returns (success, message)."""
    r = subprocess.run(
        ["git", "merge", "--no-commit", "--no-ff", branch],
        capture_output=True, text=True, check=False, cwd=project_dir,
    )
    if r.returncode == 0:
        # Commit the merge
        subprocess.run(
            ["git", "commit", "-m", f"merge: parallel dispatch slot from {branch}"],
            capture_output=True, text=True, check=False, cwd=project_dir,
        )
        return True, "merged"
    else:
        # Abort the merge
        subprocess.run(
            ["git", "merge", "--abort"],
            capture_output=True, text=True, check=False, cwd=project_dir,
        )
        return False, r.stderr.strip() or r.stdout.strip()


def fanout_dispatch(
    project_dir: str,
    prompt: str,
    n: int = 3,
    model: str | None = None,
    max_budget_per_slot: float | None = None,
    task_id: str = "parallel",
) -> FanoutResult:
    """Run N parallel SDK dispatches on isolated git worktrees.

    Args:
        project_dir: Root project directory (must be a git repo)
        prompt: Prompt to send to each agent
        n: Number of parallel agents (default 3)
        model: Model to use for each agent
        max_budget_per_slot: Max USD per slot
        task_id: Task ID for branch naming

    Returns:
        FanoutResult with per-slot results and merge status
    """
    project_dir = os.path.realpath(project_dir)
    safe_task_id = _sanitize_task_id(task_id)
    worktree_base = os.path.join(project_dir, ".superharness", "worktrees")
    os.makedirs(worktree_base, exist_ok=True)

    # Create worktree slots
    slots: list[WorktreeSlot] = []
    for i in range(n):
        branch = f"parallel/{safe_task_id}-slot-{i}"
        wt_path = os.path.join(worktree_base, f"{safe_task_id}-slot-{i}")

        # Clean up stale worktree if exists
        if os.path.exists(wt_path):
            _remove_worktree(project_dir, wt_path, branch)

        if not _create_worktree(project_dir, branch, wt_path):
            continue

        _copy_superharness_state(project_dir, wt_path)

        slots.append(WorktreeSlot(
            index=i,
            branch=branch,
            worktree_path=wt_path,
            project_dir=project_dir,
        ))

    if not slots:
        return FanoutResult(slots=[], merge_conflicts=["failed to create worktrees"])

    try:
        # Dispatch all slots in parallel
        threads: list[threading.Thread] = []
        for slot in slots:
            t = threading.Thread(
                target=_run_sdk_in_worktree,
                args=(slot, prompt, model, max_budget_per_slot),
            )
            threads.append(t)
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Collect results
        result = FanoutResult(slots=slots)
        result.total_cost_usd = sum(s.cost_usd for s in slots)
        result.total_duration_seconds = max(s.duration_seconds for s in slots) if slots else 0
    finally:
        # Clean up worktrees even on exception
        for slot in slots:
            _remove_worktree(project_dir, slot.worktree_path, slot.branch)

    return result
