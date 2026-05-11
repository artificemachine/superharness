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
import uuid
from typing import Optional

from superharness.engine.contract_io import read_contract as _read_contract
from superharness.engine.taxonomy import VALID_EFFORTS, EFFORT_ORDER


def _get_valid_agents() -> tuple[str, ...]:
    """Return all registered adapter names from the manifest directory."""
    try:
        from superharness.engine.adapter_registry import list_adapters
        adapters = list_adapters()
        return tuple(adapters) if adapters else ("claude-code", "codex-cli")
    except Exception:
        return ("claude-code", "codex-cli")


_VALID_AGENTS = _get_valid_agents()

# Effort levels that trigger orchestrator decomposition before enqueue
_DECOMPOSE_EFFORTS = {"high", "max"}


def _todo_tasks(contract: dict) -> list[dict]:
    return [
        t for t in (contract.get("tasks") or [])
        if isinstance(t, dict) and str(t.get("status", "")) == "todo"
    ]


def _classify_task(task: dict, project_dir: str) -> tuple[str, str]:
    """Return (agent, model_tier) for a task. Falls back to profile defaults.

    Tier-to-agent heuristic: mini → codex-cli (lightweight), standard/max → claude-code.
    Override with --agent to route to any registered adapter (gemini-cli, opencode, etc.).
    """
    try:
        from superharness.engine.model_router import classify_task
        tier, effort = classify_task(task, project_dir=project_dir)
        # Heuristic default: mini tasks go to codex-cli, heavier tasks to claude-code.
        agent = "codex-cli" if tier == "mini" else "claude-code"
        return agent, tier
    except Exception:
        return "claude-code", "standard"


def _read_round_skip_flag(project_dir: str) -> bool:
    """Return value of profile.yaml round_tasks_skip_plan_approval (default True)."""
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.isfile(profile_file):
        return True
    try:
        import yaml
        with open(profile_file) as f:
            doc = yaml.safe_load(f) or {}
        val = doc.get("round_tasks_skip_plan_approval")
        if val is None:
            return True
        return bool(val)
    except Exception:
        return True


def _enqueue(
    project_dir: str,
    task_id: str,
    agent: str,
    priority: int = 2,
    plan_only: bool = True,
    workflow: str = "implementation",
) -> bool:
    """Enqueue a task directly into SQLite inbox. Returns True on success.

    auto-dispatch operates on `todo` tasks, which are not valid at enqueue for
    the implementation workflow. Default to `plan_only=True` so the agent
    proposes a plan first; the operator then approves and the task re-enters
    the normal dispatch flow.

    Non-implementation workflows (review, quick, note, discussion, approval)
    have no planning phase — plan_only would advance status to plan_approved
    which is outside those workflows' allowed dispatch sets, causing a
    permanent lifecycle gate block on every subsequent dispatch attempt.
    """
    # Only implementation workflow has a planning phase.
    # All other workflows dispatch directly to execution.
    if workflow != "implementation":
        plan_only = False
    # Discussion round tasks bypass plan-only when the profile flag allows it (default: True)
    if ("/round-" in str(task_id) or "round-" in str(task_id)) and _read_round_skip_flag(project_dir):
        plan_only = False
    from datetime import datetime, timezone
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        item_id = f"{now[:8]}T{now[9:15].replace(':', '')}Z-{task_id.replace('.', '-')}-{uuid.uuid4().hex[:6]}"
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            inbox_dao.enqueue(
                conn,
                id=item_id,
                task_id=task_id,
                target_agent=agent,
                priority=priority,
                project_path=project_dir,
                plan_only=plan_only,
                now=now,
            )
            conn.commit()
            return True
        finally:
            conn.close()
    except Exception as e:
        print(f"  ERROR: failed to enqueue {task_id}: {e}", file=sys.stderr)
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
    if not os.path.exists(os.path.join(project_dir, ".superharness", "state.sqlite3")):
        print(f"auto-dispatch: project state not found at {project_dir}/.superharness/", file=sys.stderr)
        return 1

    contract, _ = _read_contract(contract_file)
    contract = contract or {}
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

        workflow = str(task.get("workflow") or "implementation")
        decompose = _should_decompose(task, effort_gate)
        decompose_note = " [→ orchestrate]" if decompose else ""

        print(f"  queue {task_id}  agent={agent}  tier={tier}{decompose_note}")

        if not dry_run:
            ok = _enqueue(project_dir, task_id, agent, workflow=workflow)
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
