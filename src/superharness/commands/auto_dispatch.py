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

from superharness.engine.taxonomy import VALID_EFFORTS, EFFORT_ORDER
from superharness.engine.orchestrator import Orchestrator
from superharness.utils.paths import is_project_initialized

import logging
logger = logging.getLogger(__name__)


def _get_valid_agents() -> tuple[str, ...]:
    """Return all registered adapter names from the manifest directory."""
    try:
        from superharness.engine.adapter_registry import list_adapters
        adapters = list_adapters()
        return tuple(adapters) if adapters else ("claude-code", "codex-cli")
    except Exception as e:
        logger.warning("auto_dispatch.py unexpected error: %s", e, exc_info=True)
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
    except Exception as e:
        logger.warning("auto_dispatch.py unexpected error: %s", e, exc_info=True)
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
    except Exception as e:
        logger.warning("auto_dispatch.py unexpected error: %s", e, exc_info=True)
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


def _register_subtasks(
    project_dir: str,
    parent_task: dict,
    subtasks: list[dict],
    agent: str,
) -> int:
    """Register subtasks in SQLite and enqueue each. Returns count of enqueued subtasks."""
    from datetime import datetime, timezone
    from dataclasses import replace
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parent_id = str(parent_task.get("id", ""))
    enqueued = 0

    conn = get_connection(project_dir)
    try:
        init_db(conn)

        for sub in subtasks:
            sub_id = str(sub.get("id", "")).strip()
            if not sub_id:
                continue
            row = TaskRow(
                id=sub_id,
                title=str(sub.get("title", f"Subtask of {parent_id}")),
                owner=str(sub.get("owner", agent)),
                status="todo",
                effort=str(sub.get("effort", "medium")),
                project_path=project_dir,
                parent_id=parent_id,
                development_method="tdd",
                acceptance_criteria=[],
                test_types=[],
                out_of_scope=[],
                definition_of_done=[],
                context=None,
                tdd=None,
                version=1,
                created_at=now,
                model_tier=str(sub.get("model_tier", "standard")),
            )
            tasks_dao.upsert(conn, row)

        # Set parent to in_progress
        parent_row = tasks_dao.get(conn, parent_id)
        if parent_row is not None:
            updated = replace(parent_row, status="in_progress", in_progress_at=now)
            tasks_dao.upsert(conn, updated)

        conn.commit()
    finally:
        conn.close()

    for sub in subtasks:
        sub_id = str(sub.get("id", "")).strip()
        if not sub_id:
            continue
        sub_agent = str(sub.get("owner", agent))
        ok = _enqueue(project_dir, sub_id, sub_agent, plan_only=True)
        if ok:
            enqueued += 1

    return enqueued


def run_auto_dispatch(
    project_dir: str,
    dry_run: bool = False,
    effort_gate: str = "high",
    agent_override: Optional[str] = None,
    orchestrate: bool = False,
) -> int:
    if not is_project_initialized(project_dir):
        print(f"auto-dispatch: project state not found at {project_dir}. Run 'shux init' first.", file=sys.stderr)
        return 1

    from superharness.engine.state_reader import get_contract_doc as _get_contract_doc
    contract = _get_contract_doc(project_dir) or {}
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

        if decompose and orchestrate:
            result = Orchestrator(project_dir).decompose(task)
            if result.subtasks:
                decompose_flagged += 1
                if dry_run:
                    print(f"  orchestrate {task_id}  subtasks={len(result.subtasks)} (dry-run, no writes)")
                    for sub in result.subtasks:
                        print(f"    subtask {sub.get('id')}  effort={sub.get('effort')}  tier={sub.get('model_tier')}")
                    enqueued += len(result.subtasks)
                else:
                    n = _register_subtasks(project_dir, task, result.subtasks, agent)
                    print(f"  orchestrate {task_id}  subtasks={len(result.subtasks)}  enqueued={n}")
                    enqueued += n
                continue
            else:
                # Empty decomposition — fall back to normal enqueue
                logger.warning("Orchestrator returned 0 subtasks for %s; falling back to direct enqueue", task_id)

        decompose_note = " [→ orchestrate]" if (decompose and not orchestrate) else ""
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

        if decompose and not orchestrate:
            decompose_flagged += 1

    label = "would enqueue" if dry_run else "enqueued"
    summary = f"\nauto-dispatch: {label} {enqueued} task(s), skipped {skipped}"
    if decompose_flagged:
        summary += f", orchestrated {decompose_flagged} task(s)"
    print(summary)
    if decompose_flagged and not orchestrate:
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
    parser.add_argument("--orchestrate", action="store_true", default=False,
                        help="Decompose high-effort tasks via Orchestrator and register subtasks")
    opts = parser.parse_args(argv)

    project = os.path.realpath(opts.project or os.getcwd())
    rc = run_auto_dispatch(
        project_dir=project,
        dry_run=opts.dry_run,
        effort_gate=opts.effort_gate,
        agent_override=opts.agent,
        orchestrate=opts.orchestrate,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
