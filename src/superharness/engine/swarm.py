"""Swarm mode — dispatch N agents, reviewer picks the best solution.

Builds on parallel_dispatch for concurrent execution. Adds a review phase
where a higher-tier model compares solutions and selects or synthesizes
the best one.
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superharness.engine.parallel_dispatch import (
    FanoutResult,
    WorktreeSlot,
    _collect_diffs,
    _create_worktree,
    _copy_superharness_state,
    _remove_worktree,
    _run_sdk_in_worktree,
    _sanitize_task_id,
    _try_merge,
)


@dataclass
class SwarmVerdict:
    """Result of swarm voting."""
    winner_index: int | None = None
    winner_branch: str = ""
    reasoning: str = ""
    merged: bool = False
    merge_error: str = ""
    fanout: FanoutResult | None = None
    review_cost_usd: float = 0.0
    total_cost_usd: float = 0.0


def _build_review_prompt(diffs: list[dict], task_prompt: str) -> str:
    """Build a prompt for the reviewer agent to compare solutions."""
    parts = [
        "You are reviewing multiple solutions to the same task.",
        "Compare them and pick the best one (or synthesize if appropriate).",
        "",
        f"## Original Task",
        task_prompt[:2000],
        "",
        "## Solutions",
        "",
    ]

    for d in diffs:
        parts.append(f"### Slot {d['index']} (branch: {d['branch']}, cost: ${d['cost_usd']:.4f})")
        parts.append(f"```diff")
        parts.append(d["stat"])
        parts.append(f"```")
        parts.append("")
        if d["diff"]:
            parts.append("Full diff (truncated):")
            parts.append(f"```diff")
            parts.append(d["diff"][:3000])
            parts.append(f"```")
        parts.append("")

    parts.extend([
        "## Your Task",
        "1. Evaluate each solution for correctness, completeness, and code quality.",
        "2. Pick the best slot index (0-based).",
        "3. Explain your reasoning briefly.",
        "",
        "Respond in this exact format:",
        "WINNER: <slot index>",
        "REASONING: <1-3 sentences>",
    ])

    return "\n".join(parts)


def _parse_review_result(output: str) -> tuple[int | None, str]:
    """Parse reviewer output for WINNER and REASONING."""
    winner = None
    reasoning = ""
    for line in output.splitlines():
        line = line.strip()
        if line.upper().startswith("WINNER:"):
            try:
                winner = int(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif line.upper().startswith("REASONING:"):
            reasoning = line.split(":", 1)[1].strip()
    return winner, reasoning


def swarm_dispatch(
    project_dir: str,
    prompt: str,
    n: int = 3,
    worker_model: str | None = None,
    reviewer_model: str = "claude-opus-4-6",
    max_budget_per_worker: float | None = None,
    max_review_budget: float = 2.00,
    task_id: str = "swarm",
    auto_merge: bool = False,
) -> SwarmVerdict:
    """Run N agents in parallel, then have a reviewer pick the best solution.

    Args:
        project_dir: Root project directory
        prompt: Task prompt for workers
        n: Number of parallel workers (default 3)
        worker_model: Model for workers (default: auto)
        reviewer_model: Model for reviewer (default: Opus)
        max_budget_per_worker: Max USD per worker
        max_review_budget: Max USD for review phase
        task_id: Task ID for naming
        auto_merge: If True, merge the winner automatically

    Returns:
        SwarmVerdict with winner, reasoning, and merge status
    """
    project_dir = os.path.realpath(project_dir)
    safe_task_id = _sanitize_task_id(task_id)
    worktree_base = os.path.join(project_dir, ".superharness", "worktrees")
    os.makedirs(worktree_base, exist_ok=True)

    # Phase 1: Create worktrees and dispatch workers
    slots: list[WorktreeSlot] = []
    for i in range(n):
        branch = f"swarm/{safe_task_id}-slot-{i}"
        wt_path = os.path.join(worktree_base, f"{safe_task_id}-slot-{i}")

        if os.path.exists(wt_path):
            _remove_worktree(project_dir, wt_path, branch)

        if not _create_worktree(project_dir, branch, wt_path):
            continue

        _copy_superharness_state(project_dir, wt_path)
        slots.append(WorktreeSlot(index=i, branch=branch, worktree_path=wt_path,
                                  project_dir=project_dir))

    if not slots:
        return SwarmVerdict(reasoning="failed to create worktrees")

    def _cleanup_all() -> None:
        for slot in slots:
            _remove_worktree(project_dir, slot.worktree_path, slot.branch)

    try:
        # Dispatch all workers in parallel
        threads: list[threading.Thread] = []
        for slot in slots:
            t = threading.Thread(
                target=_run_sdk_in_worktree,
                args=(slot, prompt, worker_model, max_budget_per_worker),
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join()
    except BaseException:
        _cleanup_all()
        raise

    fanout = FanoutResult(slots=slots)
    fanout.total_cost_usd = sum(s.cost_usd for s in slots)
    fanout.total_duration_seconds = max(s.duration_seconds for s in slots) if slots else 0

    # Phase 2: Collect diffs from completed slots
    completed = [s for s in slots if s.status == "done"]
    if not completed:
        _cleanup_all()
        return SwarmVerdict(
            fanout=fanout,
            reasoning="all workers failed",
            total_cost_usd=fanout.total_cost_usd,
        )

    if len(completed) == 1:
        # Only one succeeded — it wins by default
        winner = completed[0]
        verdict = SwarmVerdict(
            winner_index=winner.index,
            winner_branch=winner.branch,
            reasoning="single survivor (other slots failed)",
            fanout=fanout,
            total_cost_usd=fanout.total_cost_usd,
        )
        if auto_merge:
            # Commit changes in worktree first
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, check=False, cwd=winner.worktree_path,
            )
            subprocess.run(
                ["git", "commit", "-m", f"swarm: slot {winner.index} solution"],
                capture_output=True, check=False, cwd=winner.worktree_path,
            )
            ok, msg = _try_merge(project_dir, winner.branch)
            verdict.merged = ok
            verdict.merge_error = "" if ok else msg
        _cleanup_all()
        return verdict

    # Phase 3: Review — compare solutions
    diffs = _collect_diffs(project_dir, completed)
    review_prompt = _build_review_prompt(diffs, prompt)

    review_cost = 0.0
    winner_index = None
    reasoning = ""

    try:
        from superharness.engine.sdk_runner import SDKRunner
        reviewer = SDKRunner(
            project_dir=Path(project_dir),
            model=reviewer_model,
            max_budget_usd=max_review_budget,
            warm_start=False,
        )
        review_result = reviewer.run(review_prompt)
        review_cost = review_result.get("cost_usd", 0.0)
        winner_index, reasoning = _parse_review_result(review_result.get("output", ""))
    except Exception as e:
        reasoning = f"review failed: {e}"

    # Validate winner index
    valid_indices = {s.index for s in completed}
    if winner_index not in valid_indices:
        # Default to cheapest completed slot
        winner_index = min(completed, key=lambda s: s.cost_usd).index
        reasoning += f" (reviewer pick invalid, defaulting to cheapest slot {winner_index})"

    winner_slot = next(s for s in slots if s.index == winner_index)

    verdict = SwarmVerdict(
        winner_index=winner_index,
        winner_branch=winner_slot.branch,
        reasoning=reasoning,
        fanout=fanout,
        review_cost_usd=review_cost,
        total_cost_usd=fanout.total_cost_usd + review_cost,
    )

    # Phase 4: Merge winner if auto_merge
    if auto_merge and winner_slot.worktree_path:
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, check=False, cwd=winner_slot.worktree_path,
        )
        subprocess.run(
            ["git", "commit", "-m", f"swarm: slot {winner_index} solution (winner)"],
            capture_output=True, check=False, cwd=winner_slot.worktree_path,
        )
        ok, msg = _try_merge(project_dir, winner_slot.branch)
        verdict.merged = ok
        verdict.merge_error = "" if ok else msg

    # Cleanup all worktrees
    _cleanup_all()

    return verdict
