"""auto-dispatch — scan todo tasks, classify, and enqueue each to the best agent.

Reads the contract, finds all tasks in `todo` status, classifies each via the
model router (Haiku), resolves the best agent+model, and enqueues them into
inbox.yaml. The watcher picks them up within the normal poll interval.

Usage:
  shux auto-dispatch [--project DIR] [--dry-run] [--effort-gate high] [--agent claude-code]
"""
from __future__ import annotations

import os
import sys
from typing import Optional

import yaml
from superharness.engine.taxonomy import VALID_EFFORTS, EFFORT_ORDER


_VALID_AGENTS = ("claude-code", "codex-cli")

# Effort levels that trigger orchestrator decomposition before enqueue
_DECOMPOSE_EFFORTS = {"high", "max"}


def _load_contract(contract_file: str) -> dict:
    try:
        with open(contract_file, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def _todo_tasks(contract: dict) -> list[dict]:
    return [
        t for t in (contract.get("tasks") or [])
        if isinstance(t, dict) and str(t.get("status", "")) == "todo"
    ]


def _classify_task(task: dict, project_dir: str) -> tuple[str, str]:
    """Return (agent, model_tier) for a task. Falls back to profile defaults."""
    try:
        from superharness.engine.model_router import classify_task
        tier, effort = classify_task(task, project_dir=project_dir)
        # Map tier → preferred agent (mini → codex-cli, standard/max → claude-code)
        agent = "codex-cli" if tier == "mini" else "claude-code"
        return agent, tier
    except Exception:
        return "claude-code", "standard"


def _enqueue(project_dir: str, task_id: str, agent: str, priority: int = 5) -> bool:
    """Enqueue a task into inbox.yaml. Returns True on success."""
    try:
        from superharness.commands.inbox_enqueue import main as enqueue_main
        enqueue_main([
            "--project", project_dir,
            "--task", task_id,
            "--to", agent,
            "--priority", str(priority),
        ])
        return True
    except SystemExit as e:
        return e.code == 0
    except Exception:
        return False


def _should_decompose(task: dict, effort_gate: str) -> bool:
    """Return True if the task effort meets or exceeds the decomposition gate."""
    task_effort = str(task.get("effort") or "medium")
    try:
        gate_idx = EFFORT_ORDER.index(effort_gate)
        task_idx = EFFORT_ORDER.index(task_effort)
        return task_idx >= gate_idx
    except ValueError:
        return False


def run_auto_dispatch(
    project_dir: str,
    dry_run: bool = False,
    effort_gate: str = "high",
    agent_override: Optional[str] = None,
) -> int:
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.exists(contract_file):
        print(f"auto-dispatch: contract not found at {contract_file}", file=sys.stderr)
        return 1

    contract = _load_contract(contract_file)
    tasks = _todo_tasks(contract)

    if not tasks:
        print("auto-dispatch: no todo tasks found — nothing to enqueue")
        return 0

    print(f"auto-dispatch: found {len(tasks)} todo task(s)")
    if dry_run:
        print("auto-dispatch: DRY RUN — no changes will be made")

    enqueued = 0
    skipped = 0
    decompose_flagged = 0

    for task in tasks:
        task_id = str(task.get("id", "")).strip()
        if not task_id:
            continue

        # Respect blocked_by — skip tasks with unresolved blockers
        blocked_by = task.get("blocked_by") or task.get("dependency")
        if blocked_by and str(blocked_by).lower() not in ("none", "null", "~", ""):
            print(f"  skip  {task_id} (blocked by {blocked_by})")
            skipped += 1
            continue

        agent, tier = _classify_task(task, project_dir)
        if agent_override:
            agent = agent_override

        decompose = _should_decompose(task, effort_gate)
        decompose_note = " [→ orchestrate]" if decompose else ""

        print(f"  queue {task_id}  agent={agent}  tier={tier}{decompose_note}")

        if not dry_run:
            ok = _enqueue(project_dir, task_id, agent)
            if ok:
                enqueued += 1
            else:
                print(f"  ERROR: failed to enqueue {task_id}", file=sys.stderr)
                skipped += 1
        else:
            enqueued += 1  # count as "would enqueue" in dry-run

        if decompose:
            decompose_flagged += 1

    label = "would enqueue" if dry_run else "enqueued"
    print(f"\nauto-dispatch: {label} {enqueued} task(s), skipped {skipped}")
    if decompose_flagged:
        print(f"auto-dispatch: {decompose_flagged} task(s) flagged for orchestrator decomposition "
              f"(effort >= {effort_gate}) — re-dispatch with --orchestrate to decompose")

    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="auto-dispatch",
        description="Scan todo tasks, classify each, and enqueue to the best agent.",
    )
    parser.add_argument("-p", "--project", default=None,
                        help="Project directory (default: cwd)")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Show what would be enqueued without making changes")
    parser.add_argument("--effort-gate", default="high",
                        choices=list(VALID_EFFORTS),
                        help="Effort threshold that flags a task for orchestrator decomposition "
                             "(default: high)")
    parser.add_argument("--agent", default=None, choices=list(_VALID_AGENTS),
                        help="Override agent for all tasks (skip auto-classification)")
    opts = parser.parse_args(argv)

    project = os.path.realpath(opts.project or os.getcwd())
    rc = run_auto_dispatch(
        project_dir=project,
        dry_run=opts.dry_run,
        effort_gate=opts.effort_gate,
        agent_override=opts.agent,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
