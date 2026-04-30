"""Python port of task.sh — create/delete/status operations on contract tasks.

Output format is byte-for-byte identical to the Ruby version.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional

from superharness.engine.contract_io import write_contract as _write_contract, read_contract as _read_contract
from superharness.engine.taxonomy import VALID_EFFORTS
from superharness.engine.next_action import ALL_STATUSES

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

VALID_OWNERS = {"owner", "claude-code", "codex-cli", "gemini-cli"}
VALID_CREATE_STATUSES = {"todo", "in_progress", "pending_user_approval", "done"}
VALID_WORKFLOWS = {"implementation", "quick", "discussion", "review", "approval", "note"}
VALID_AUTONOMY = {"ai_driven", "oversight", "hands_on"}
TOKEN_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _load_policy_from_profile(project_path: str) -> tuple[str, bool]:
    """Load (autonomy, require_tdd) defaults from project profile.yaml.

    Returns the safe defaults (ai_driven, True) when profile.yaml is absent,
    unreadable, or missing fields. Never raises.
    """
    profile_path = os.path.join(project_path, ".superharness", "profile.yaml")
    if not os.path.exists(profile_path):
        return ("ai_driven", True)
    try:
        import yaml as _yaml
        with open(profile_path) as _f:
            profile = _yaml.safe_load(_f) or {}
    except Exception:
        return ("ai_driven", True)
    autonomy = str(profile.get("autonomy") or "ai_driven")
    if autonomy not in VALID_AUTONOMY:
        autonomy = "ai_driven"
    wf = profile.get("workflow")
    if isinstance(wf, dict) and "require_tdd" in wf:
        require_tdd = bool(wf["require_tdd"])
    else:
        require_tdd = True
    return (autonomy, require_tdd)


def _validate_token(name: str, value: str) -> None:
    if not value:
        _abort(f"{name} must not be empty", 2)
    if "\n" in value or "\r" in value or "\t" in value:
        _abort(f"{name} contains control characters", 2)
    if not TOKEN_RE.match(value):
        _abort(f"{name} must match ^[A-Za-z0-9._/-]+$", 2)


_JSON_MODE = False
_JSON_CTX: dict = {}


def _abort(msg: str, code: int = 1) -> None:
    if _JSON_MODE:
        from superharness.utils.json_output import emit_error
        emit_error(msg, exit_code=code, **_JSON_CTX)
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# YAML read / write helpers
# ---------------------------------------------------------------------------


def _get_tasks(doc: object, path: str) -> list:
    if not isinstance(doc, dict):
        _abort("contract.yaml must be a mapping")
    tasks = doc.get("tasks")  # type: ignore[union-attr]
    if tasks is None:
        return []
    if not isinstance(tasks, list):
        _abort("contract tasks must be a sequence")
    return tasks


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

def _parse_blocked_by(value: str | list | None) -> str | list:
    """Normalise blocked_by input to 'none', a single ID, or a list."""
    if value is None or value == "" or value == "none":
        return "none"
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    s = str(value).strip()
    if "," in s:
        return [v.strip() for v in s.split(",") if v.strip()]
    return s


def create(
    contract_file: str,
    task_id: str,
    title: str,
    owner: str,
    status: str,
    project_path: str,
    dependency: Optional[str] = None,
    criteria: Optional[list] = None,
    blocked_by: str | list | None = None,
    tdd_red: str = "",
    tdd_green: str = "",
    tdd_refactor: str = "",
    workflow: str = "quick",
    development_method: str = "",
    effort: str = "medium",
    test_types: Optional[list[str]] = None,
    out_of_scope: Optional[list[str]] = None,
    definition_of_done: Optional[list[str]] = None,
    context: Optional[str] = None,
    timeout_minutes: Optional[int] = None,
    plan: Optional[dict] = None,
    ship_on_complete: bool = False,
    autonomy: Optional[str] = None,
    require_tdd: Optional[bool] = None,
) -> int:
    _validate_token("task id", task_id)
    if dependency:
        _validate_token("dependency id", dependency)

    if owner not in VALID_OWNERS:
        _abort(f"owner must be one of: {', '.join(sorted(VALID_OWNERS))}", 2)
    if status not in VALID_CREATE_STATUSES:
        _abort("status must be todo, in_progress, pending_user_approval, or done", 2)
    if workflow and workflow not in VALID_WORKFLOWS:
        _abort(
            f"workflow must be one of: {', '.join(sorted(VALID_WORKFLOWS))}",
            2,
        )
    # development_method accepts any string (no hardcoded enum)
    if effort and effort not in VALID_EFFORTS:
        _abort(f"effort must be one of: {', '.join(sorted(VALID_EFFORTS))}", 2)
    if autonomy is not None and autonomy not in VALID_AUTONOMY:
        _abort(
            f"autonomy must be one of: {', '.join(sorted(VALID_AUTONOMY))}",
            2,
        )

    # Stamp policy from profile when not explicitly overridden on CLI
    profile_autonomy, profile_require_tdd = _load_policy_from_profile(project_path)
    if autonomy is None:
        autonomy = profile_autonomy
    if require_tdd is None:
        require_tdd = profile_require_tdd

    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    # Check duplicate
    if any(isinstance(t, dict) and str(t.get("id", "")) == task_id for t in tasks):
        _abort(f"task '{task_id}' already exists")

    # Check dependency (legacy single-ID field)
    if dependency:
        if dependency == task_id:
            _abort(f"task '{task_id}' cannot depend on itself")
        if not any(isinstance(t, dict) and str(t.get("id", "")) == dependency for t in tasks):
            _abort(f"dependency task '{dependency}' not found")

    # Validate blocked_by IDs
    blocked = _parse_blocked_by(blocked_by)
    if blocked != "none":
        ids_to_check = blocked if isinstance(blocked, list) else [blocked]
        existing_ids = {str(t.get("id", "")) for t in tasks if isinstance(t, dict)}
        for bid in ids_to_check:
            if bid == task_id:
                _abort(f"task '{task_id}' cannot be blocked by itself")
            if bid not in existing_ids:
                _abort(f"blocked_by task '{bid}' not found")

    task: dict = {}

    task["id"] = task_id
    task["title"] = title
    task["owner"] = owner
    task["status"] = status
    task["project_path"] = project_path
    task["blocked_by"] = blocked
    if workflow:
        task["workflow"] = workflow
    if development_method:
        task["development_method"] = development_method
    task["autonomy"] = autonomy
    task["require_tdd"] = bool(require_tdd)
    if dependency:
        task["dependency"] = dependency
    if criteria:
        task["acceptance_criteria"] = list(criteria)
    if effort:
        task["effort"] = effort
    if test_types:
        task["test_types"] = list(test_types)
    if out_of_scope:
        task["out_of_scope"] = list(out_of_scope)
    if definition_of_done:
        task["definition_of_done"] = list(definition_of_done)
    if context:
        task["context"] = context
    if timeout_minutes is not None:
        task["timeout_minutes"] = timeout_minutes
    if ship_on_complete:
        task["ship_on_complete"] = True
    # Write as "tdd" key for backward compat (Pydantic reads via alias into plan field)
    if plan:
        task["tdd"] = dict(plan)
    elif tdd_red or tdd_green or tdd_refactor:
        tdd: dict = {}
        if tdd_red:
            tdd["red"] = tdd_red
        if tdd_green:
            tdd["green"] = tdd_green
        if tdd_refactor:
            tdd["refactor"] = tdd_refactor
        task["tdd"] = tdd

    tasks.append(task)
    doc["tasks"] = tasks  # type: ignore[index]
    _write_contract(contract_file, doc)

    print(f"Created task '{task_id}' (owner={owner}, status={status}, blocked_by={blocked})")
    return 0


def archive_done(contract_file: str, ids: list[str] | None = None) -> int:
    """Flip every done task (or specific ids) to archived in one pass.

    Bypasses the per-task actor/owner guard used by status_update, because
    this is a bulk admin operation run by the operator (e.g. end-of-session
    cleanup). Archived tasks remain in contract.yaml; renderers hide them
    by default.
    """
    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    targets = set(ids) if ids else None
    flipped: list[str] = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("id", ""))
        if targets is not None and tid not in targets:
            continue
        if str(t.get("status", "")) != "done":
            continue
        t["status"] = "archived"
        flipped.append(tid)

    if not flipped:
        print("No done tasks to archive.")
        return 0

    _write_contract(contract_file, doc)
    print(f"Archived {len(flipped)} task(s):")
    for tid in flipped:
        print(f"  - {tid}")
    return 0


def delete(contract_file: str, task_id: str) -> int:
    _validate_token("task id", task_id)

    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    before = len(tasks)
    new_tasks = [t for t in tasks if not (isinstance(t, dict) and str(t.get("id", "")) == task_id)]
    if len(new_tasks) == before:
        _abort(f"task '{task_id}' not found")

    doc["tasks"] = new_tasks  # type: ignore[index]
    _write_contract(contract_file, doc)
    print(f"Deleted task '{task_id}'")
    return 0


def _cascade_unblocked_tasks(contract_file: str, finished_task_id: str) -> None:
    """Scan contract for tasks blocked by finished_task_id and enqueue them if unblocked."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    
    # Check if auto_dispatch is enabled globally
    if not os.path.exists(profile_file):
        return
    try:
        import yaml as _yaml
        with open(profile_file) as _f:
            profile = _yaml.safe_load(_f) or {}
        if not profile.get("auto_dispatch"):
            return
    except Exception:
        return

    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)
    
    # Map all tasks for quick status lookup
    status_map = {str(t.get("id", "")): str(t.get("status", "")) for t in tasks if isinstance(t, dict)}
    
    # Find all tasks that were blocked by the finished task
    dependents = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        blocked_by = _parse_blocked_by(t.get("blocked_by"))
        if blocked_by == "none":
            continue
        ids = blocked_by if isinstance(blocked_by, list) else [blocked_by]
        if finished_task_id in ids:
            dependents.append(t)
            
    if not dependents:
        return

    # Check if each dependent is now fully unblocked
    from superharness.engine.inbox import _deps_satisfied
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    for t in dependents:
        tid = str(t.get("id", ""))
        status = str(t.get("status", ""))
        
        # Only cascade to 'todo' or 'plan_approved' tasks
        if status not in ("todo", "plan_approved"):
            continue
            
        if _deps_satisfied(contract_file, tid):
            # Instant enqueue!
            owner = str(t.get("owner", "claude-code"))
            autonomy = str(t.get("autonomy") or "ai_driven")
            
            # For todo tasks, only auto-enqueue if autonomous
            if status == "todo" and autonomy != "autonomous" and profile.get("autonomy") != "autonomous":
                continue

            item_id = f"cascade-{uuid.uuid4().hex[:6]}"
            plan_only = (status == "todo")
            
            # Call engine/inbox.py enqueue via subprocess
            import subprocess
            cmd = [
                sys.executable, "-m", "superharness.engine.inbox", "enqueue",
                "--file", inbox_file,
                "--id", item_id,
                "--to", owner,
                "--task", tid,
                "--project", project_dir,
                "--priority", "2",
                "--created-at", now
            ]
            if plan_only:
                cmd.append("--plan-only")
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                print(f"cascading-dispatch: task {tid} unblocked and enqueued (item {item_id}, plan_only={plan_only})")


def _load_latest_plan_handoff(contract_file: str, task_id: str) -> dict | None:
    """Return the latest phase=plan handoff for a task, or None if none found.

    Used by iter 5 plan quality gate before auto-approval.
    """
    import glob

    import yaml as _yaml

    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
    handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
    if not os.path.isdir(handoffs_dir):
        return None

    candidates = sorted(glob.glob(os.path.join(handoffs_dir, f"*{task_id}*plan*")), reverse=True)
    candidates += [
        p for p in sorted(glob.glob(os.path.join(handoffs_dir, f"*{task_id}*.yaml")), reverse=True)
        if p not in candidates
    ]
    for path in candidates:
        try:
            with open(path, encoding="utf-8") as f:
                h = _yaml.safe_load(f.read()) or {}
            if str(h.get("task", "")) == task_id and h.get("phase") == "plan":
                return h
        except Exception:
            continue
    return None


def _enqueue_for_implementation(contract_file: str, task_id: str) -> None:
    """Instantly enqueue a plan_approved task for implementation."""
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)
    task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
    if not task:
        return
        
    owner = str(task.get("owner", "claude-code"))
    item_id = f"auto-impl-{uuid.uuid4().hex[:6]}"
    
    import subprocess
    cmd = [
        sys.executable, "-m", "superharness.engine.inbox", "enqueue",
        "--file", inbox_file,
        "--id", item_id,
        "--to", owner,
        "--task", task_id,
        "--project", project_dir,
        "--priority", "2",
        "--created-at", now
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        print(f"auto-dispatch: task {task_id} enqueued for implementation (item {item_id})")


def set_owner(contract_file: str, task_id: str, new_owner: str) -> int:
    """Update task owner and clean up any active inbox items for the old owner."""
    import signal as _signal

    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
    if task is None:
        _abort(f"task '{task_id}' not found")

    old_owner = task.get("owner", "unknown")
    if old_owner == new_owner:
        print(f"Task '{task_id}' is already owned by '{new_owner}'")
        return 0

    task["owner"] = new_owner
    _write_contract(contract_file, doc)
    print(f"Reassigned task '{task_id}': {old_owner} → {new_owner}")

    # Scan inbox for active items that were dispatched to the old owner and cancel them.
    harness_dir = os.path.dirname(contract_file)
    project_dir = os.path.dirname(harness_dir)
    inbox_file = os.path.join(harness_dir, "inbox.yaml")

    if not os.path.exists(inbox_file):
        return 0

    from superharness.engine.inbox import _inbox_lock, _load_items, _write_items

    ACTIVE = {"pending", "launched", "running"}
    removed_ids: list[str] = []

    with _inbox_lock(inbox_file):
        items = _load_items(inbox_file)
        keep = []
        for item in items:
            if not isinstance(item, dict):
                keep.append(item)
                continue
            if str(item.get("task", "")) == task_id and item.get("status") in ACTIVE:
                pid_str = item.get("pid")
                if pid_str:
                    try:
                        os.kill(int(pid_str), _signal.SIGTERM)
                        print(f"  stopped pid={pid_str} (item {item['id']})")
                    except (ProcessLookupError, PermissionError, ValueError):
                        pass
                removed_ids.append(str(item["id"]))
            else:
                keep.append(item)
        if removed_ids:
            _write_items(inbox_file, keep)

    if removed_ids:
        print(f"  removed {len(removed_ids)} inbox item(s) for old owner '{old_owner}': {', '.join(removed_ids)}")

    # Re-enqueue to the new owner when the task is dispatch-ready.
    if removed_ids:
        from superharness.engine.next_action import (
            allowed_statuses_for_workflow,
            plan_only_allowed_statuses,
        )
        from superharness.commands.inbox_enqueue import enqueue_cmd

        task_status = str(task.get("status", ""))
        task_workflow = str(task.get("workflow", "implementation"))
        dispatch_ready = task_status in allowed_statuses_for_workflow(task_workflow)
        plan_only_ready = task_status in plan_only_allowed_statuses(task_workflow)

        if dispatch_ready or plan_only_ready:
            plan_only = not dispatch_ready and plan_only_ready
            try:
                enqueue_cmd(
                    project_dir=project_dir,
                    task_id=task_id,
                    target=new_owner,
                    item_id=None,
                    priority=2,
                    plan_only=plan_only,
                    force_reassign=True,
                )
                suffix = " (plan-only)" if plan_only else ""
                print(f"  re-enqueued '{task_id}' to '{new_owner}'{suffix}")
            except SystemExit as exc:
                if exc.code != 0:
                    print(f"  warning: re-enqueue failed — task is reassigned but not in inbox", file=sys.stderr)
        else:
            print(f"  task status '{task_status}' is not dispatch-ready — not re-enqueued")

    return 0


def status_update(
    contract_file: str,
    task_id: str,
    status: str,
    actor: str,
    reason: str = "",
    summary: str = "",
    _recursion_guard: bool = False,
) -> int:
    _validate_token("task id", task_id)

    if status not in ALL_STATUSES:
        _abort(f"status must be one of: {', '.join(sorted(ALL_STATUSES))}", 2)

    if status in ("failed", "stopped") and not reason:
        _abort(f"error: --reason is required when status={status}", 2)

    if status in ("todo", "in_progress", "pending_user_approval", "done") and not summary:
        _abort(f"error: --summary is required when status={status}", 2)

    doc, _ = _read_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
    if task is None:
        _abort(f"task '{task_id}' not found")

    owner = str(task.get("owner", ""))
    if not owner:
        _abort(f"task '{task_id}' has no owner set")

    dependency = str(task.get("dependency", "") or "")

    if actor != owner and not _recursion_guard:
        _abort(f"forbidden: actor '{actor}' cannot update task '{task_id}' owned by '{owner}'")  # shipguard:ignore PY-007

    if dependency and status in ("in_progress", "done"):
        dep_task = next(
            (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == dependency),
            None
        )
        if dep_task is None:
            _abort(f"task '{task_id}' dependency '{dependency}' not found")
        dep_status = str(dep_task.get("status", ""))
        if dep_status not in ("done", "archived"):
            _abort(f"blocked: task '{task_id}' depends on '{dependency}' (status={dep_status})")

    # Scope guard: warn on plan_approved if task looks too large to dispatch as one unit
    if status == "plan_approved":
        ac = task.get("acceptance_criteria")
        ac_count = len(ac) if isinstance(ac, list) else 0
        plan = task.get("plan") or task.get("tdd")
        has_plan = bool(plan and isinstance(plan, dict))
        if ac_count > 3:
            print(
                f"⚠  Scope warning: task '{task_id}' has {ac_count} acceptance criteria (threshold: 3).\n"
                f"   Consider decomposing into subtasks before dispatch.\n"
                f"   Use: shux delegate {task_id} --orchestrate  (auto-decompose via Opus)\n"
                f"   Or: manually split into smaller tasks with blocked_by ordering.",
                file=sys.stderr,
            )

    task["status"] = status

    if status in ("failed", "stopped") and reason:
        task["stopped_reason"] = reason
        task["stopped_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        task.pop("stopped_reason", None)  # type: ignore[union-attr]
        task.pop("stopped_at", None)  # type: ignore[union-attr]

    if summary:
        task["summary"] = summary
    elif status not in ("failed", "stopped"):
        task.pop("summary", None)  # type: ignore[union-attr]

    _write_contract(contract_file, doc)

    # Auto-approve hook: plan_proposed → plan_approved when task.autonomy=ai_driven
    # or when auto_approve_plans is true in profile.yaml
    if status == "plan_proposed" and not _recursion_guard:
        # Load profile to check for global auto-approval policy
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
        profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
        auto_approve = False
        if os.path.exists(profile_path):
            try:
                import yaml as _yaml
                with open(profile_path) as _f:
                    profile = _yaml.safe_load(_f) or {}
                    auto_approve = bool(profile.get("auto_approve_plans", False))
            except Exception:
                pass

        task_autonomy = str(task.get("autonomy") or "ai_driven")
        if task_autonomy == "ai_driven" or auto_approve:
            # Plan quality gate (iter 5 of auto-mode-gap-plan): only auto-approve
            # plans that pass structural checks. Failing plans stay plan_proposed
            # with a validation_failures field so the operator sees them with reason.
            try:
                from superharness.engine.plan_validator import validate_plan
                plan_handoff = _load_latest_plan_handoff(contract_file, task_id)
                if plan_handoff:
                    result = validate_plan(plan_handoff, task)  # type: ignore[arg-type]
                    if not result.passed:
                        print(
                            f"Auto-approve blocked for '{task_id}': "
                            + "; ".join(result.failures)
                        )
                        # Stamp validation_failures on the task for dashboard surface
                        task["validation_failures"] = result.failures  # type: ignore[index]
                        _write_contract(contract_file, doc)
                        return
            except Exception as e:
                print(f"Warning: plan validation skipped: {e}", file=sys.stderr)

            reason = "auto-approved per task autonomy setting" if task_autonomy == "ai_driven" else "auto-approved per project policy"
            print(f"Auto-approving task '{task_id}' ({reason})")
            status_update(
                contract_file, task_id, "plan_approved",
                actor="ai-autonomy",
                summary=reason,
                _recursion_guard=True,
            )

            # Instant re-enqueue for implementation!
            try:
                _enqueue_for_implementation(contract_file, task_id)
            except Exception as e:
                print(f"Warning: auto-dispatch re-enqueue failed: {e}", file=sys.stderr)

    # Subtask resolution gate for done transition
    if status == "done":
        try:
            from superharness.engine.subtask_gate import (
                evaluate_subtask_gate_from_disk,
                format_gate_error,
            )
            _task_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
            gate = evaluate_subtask_gate_from_disk(task, _task_project_dir)
            if gate.enabled and gate.blocking:
                _abort(format_gate_error(task_id, gate))
        except ImportError:
            pass

    # Warn about unverified acceptance criteria when marking done
    if status == "done":
        ac = task.get("acceptance_criteria")
        if ac and isinstance(ac, list) and ac:
            print(f"Warning: task '{task_id}' has acceptance criteria — verify before closing:", file=sys.stderr)
            for c in ac:
                print(f"  - {c}", file=sys.stderr)

        # Cascading Dispatch: instantly enqueue newly unblocked tasks
        try:
            _cascade_unblocked_tasks(contract_file, task_id)
        except Exception as e:
            print(f"Warning: cascading dispatch failed: {e}", file=sys.stderr)

        # Extract and persist skill for future dispatch context
        try:
            from superharness.engine.skill_extractor import record_skill
            skill = record_skill(project_dir, dict(task))
            if skill:
                print(f"Skill recorded: [{skill.category}] {skill.title}")
        except Exception:
            pass

    print(f"Updated task '{task_id}' status={status} by actor={actor}")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="task",
        description="Manage contract tasks",
        add_help=True,
    )
    sub = parser.add_subparsers(dest="subcmd")

    # create
    p_create = sub.add_parser("create", add_help=True)
    p_create.add_argument("--project", "-p", default=None)
    p_create.add_argument("--id", dest="task_id", default=None,
                          help="Task ID (auto-generated as t-XXXXXX if omitted)")
    p_create.add_argument("--title", required=True)
    p_create.add_argument("--owner", default=None)
    p_create.add_argument("--status", default="todo")
    p_create.add_argument("--dependency", default="")
    p_create.add_argument("--blocked-by", dest="blocked_by", default=None,
                          help="Task ID(s) this task is blocked by (comma-separated, or 'none')")
    p_create.add_argument("--tdd-red", dest="tdd_red", default="",
                          help="TDD red phase: failing tests that define done")
    p_create.add_argument("--tdd-green", dest="tdd_green", default="",
                          help="TDD green phase: minimal code to make tests pass")
    p_create.add_argument("--tdd-refactor", dest="tdd_refactor", default="",
                          help="TDD refactor phase: cleanup after green, no new behaviour")
    p_create.add_argument("--workflow", default="quick",
                          help="Optional workflow template: implementation, quick, discussion, review, approval, note (default: quick)")
    p_create.add_argument("--development-method", dest="development_method", default="",
                          help="Optional development method: tdd, bdd, sdd, none")
    p_create.add_argument("--criteria", action="append", default=[], metavar="CRITERION",
                          help="Acceptance criterion (repeat for multiple)")
    p_create.add_argument("--effort", default="medium",
                          help="Effort level: low, medium, high, max (default: medium)")
    p_create.add_argument("--test-types", dest="test_types", default=None,
                          help="Comma-separated test types (e.g. unit,integration,e2e)")
    p_create.add_argument("--out-of-scope", dest="out_of_scope", action="append", default=[],
                          help="Out of scope item (repeat for multiple)")
    p_create.add_argument("--definition-of-done", dest="definition_of_done", action="append", default=[],
                          help="Definition of done item (repeat for multiple)")
    p_create.add_argument("--context", default=None,
                          help="Operator-authored context string injected into dispatch prompt")
    p_create.add_argument("--timeout-minutes", dest="timeout_minutes", type=int, default=None,
                          help="Timeout in minutes for task execution")
    p_create.add_argument("--bdd-given", dest="bdd_given", default="",
                          help="BDD given phase")
    p_create.add_argument("--bdd-when", dest="bdd_when", default="",
                          help="BDD when phase")
    p_create.add_argument("--bdd-then", dest="bdd_then", default="",
                          help="BDD then phase")
    p_create.add_argument("--ship-on-complete", dest="ship_on_complete",
                          action="store_true", default=False,
                          help="Agent must run /ship commit before report_ready; watcher validates PR URL")
    p_create.add_argument("--autonomy", default=None,
                          choices=sorted(VALID_AUTONOMY),
                          help="Override project autonomy (default: read from profile.yaml or ai_driven)")
    p_create.add_argument("--require-tdd", dest="require_tdd",
                          action="store_true", default=None,
                          help="Force require_tdd=true on this task (default: read from profile)")
    p_create.add_argument("--no-require-tdd", dest="require_tdd",
                          action="store_false", default=None,
                          help="Force require_tdd=false on this task")

    # delete
    p_delete = sub.add_parser("delete", add_help=True)
    p_delete.add_argument("--project", "-p", default=None)
    p_delete.add_argument("--id", dest="task_id", required=True)

    # archive-done: bulk-flip every done task to archived
    p_archive = sub.add_parser("archive-done", add_help=True,
                                help="Move every done task (or specific --id) to archived")
    p_archive.add_argument("--project", "-p", default=None)
    p_archive.add_argument("--id", action="append", dest="ids", default=None,
                           help="Specific task id(s) to archive (repeat). Default: all done tasks.")

    # status
    p_status = sub.add_parser("status", add_help=True)
    p_status.add_argument("--project", "-p", default=None)
    p_status.add_argument("--id", dest="task_id", required=True)
    _valid_status_hint = "{" + "|".join(sorted(ALL_STATUSES)) + "}"
    p_status.add_argument("--status", required=True, metavar=_valid_status_hint,
                          help=f"Lifecycle status. One of: {', '.join(sorted(ALL_STATUSES))}")
    p_status.add_argument("--actor", required=True)
    p_status.add_argument("--reason", default="")
    p_status.add_argument("--summary", default="")
    p_status.add_argument("--json", action="store_true", default=False,
                          help="Emit machine-readable JSON on stdout instead of human text.")

    # set-owner
    p_owner = sub.add_parser("set-owner", help="Change the owner (agent) of a task")
    p_owner.add_argument("--project", "-p", default=None)
    p_owner.add_argument("--id", dest="task_id", required=True)
    p_owner.add_argument("--owner", required=True, choices=list(VALID_OWNERS))

    opts = parser.parse_args(argv)
    if not opts.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.exists(contract_file):
        _abort(f"Missing contract file: {contract_file}")

    if opts.subcmd == "create":
        owner = opts.owner or ""
        if not owner:
            # Try profile.yaml primary_agent
            profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
            if os.path.exists(profile_file):
                try:
                    import yaml as _yaml
                    with open(profile_file) as _f:
                        _profile = _yaml.safe_load(_f) or {}
                    owner = str(_profile.get("primary_agent") or "")
                except Exception:
                    pass
        if not owner:
            # Prompt via stdin
            try:
                if sys.stdin.isatty():
                    sys.stderr.write(f"Task owner ({'|'.join(sorted(VALID_OWNERS))}): ")
                    sys.stderr.flush()
                owner = sys.stdin.readline().strip()
            except (EOFError, OSError):
                pass
        if not owner:
            _abort("--owner is required (or set in profile.yaml)", 2)
        task_id = opts.task_id or f"t-{uuid.uuid4().hex[:6]}"
        # Build plan dict from method-specific flags
        plan = None
        if opts.bdd_given or opts.bdd_when or opts.bdd_then:
            plan = {}
            if opts.bdd_given:
                plan["given"] = opts.bdd_given
            if opts.bdd_when:
                plan["when"] = opts.bdd_when
            if opts.bdd_then:
                plan["then"] = opts.bdd_then
        # Parse test_types from comma-separated string
        test_types = None
        if opts.test_types:
            test_types = [t.strip() for t in opts.test_types.split(",") if t.strip()]
        rc = create(
            contract_file,
            task_id=task_id,
            title=opts.title,
            owner=owner,
            status=opts.status,
            project_path=project_dir,
            dependency=opts.dependency or None,
            criteria=opts.criteria or None,
            blocked_by=opts.blocked_by,
            tdd_red=opts.tdd_red,
            tdd_green=opts.tdd_green,
            tdd_refactor=opts.tdd_refactor,
            workflow=opts.workflow,
            development_method=opts.development_method,
            effort=opts.effort,
            test_types=test_types,
            out_of_scope=opts.out_of_scope or None,
            definition_of_done=opts.definition_of_done or None,
            context=opts.context,
            timeout_minutes=opts.timeout_minutes,
            plan=plan,
            ship_on_complete=opts.ship_on_complete,
            autonomy=opts.autonomy,
            require_tdd=opts.require_tdd,
        )
        sys.exit(rc)

    elif opts.subcmd == "delete":
        rc = delete(contract_file, task_id=opts.task_id)
        sys.exit(rc)

    elif opts.subcmd == "archive-done":
        rc = archive_done(contract_file, ids=opts.ids)
        sys.exit(rc)

    elif opts.subcmd == "status":
        global _JSON_MODE, _JSON_CTX
        if getattr(opts, "json", False):
            _JSON_MODE = True
            _JSON_CTX = {"task_id": opts.task_id, "new_status": opts.status, "actor": opts.actor}

        # Capture old status for the JSON payload
        old_status = None
        if _JSON_MODE:
            try:
                _doc, _ = _read_contract(contract_file)
                _tasks = _get_tasks(_doc, contract_file)
                _t = next((t for t in _tasks if isinstance(t, dict) and str(t.get("id", "")) == opts.task_id), None)
                if _t is not None:
                    old_status = str(_t.get("status", ""))
            except SystemExit:
                raise
            except Exception:
                pass

        # Pre-validate before calling status_update so shell exit codes match
        if opts.status in ("failed", "stopped") and not opts.reason:
            _abort(f"error: --reason is required when status={opts.status}", 2)
        if opts.status in ("todo", "in_progress", "pending_user_approval", "done") and not opts.summary:
            _abort(f"error: --summary is required when status={opts.status}", 2)

        # In JSON mode, temporarily suppress stdout prints from status_update
        if _JSON_MODE:
            import io
            _orig_stdout = sys.stdout
            sys.stdout = io.StringIO()
            try:
                rc = status_update(
                    contract_file,
                    task_id=opts.task_id,
                    status=opts.status,
                    actor=opts.actor,
                    reason=opts.reason or "",
                    summary=opts.summary or "",
                )
            finally:
                sys.stdout = _orig_stdout
            _sync_inbox_after_status(project_dir, opts.task_id, opts.status)
            from superharness.utils.json_output import emit_json
            emit_json({
                "task_id": opts.task_id,
                "old_status": old_status,
                "new_status": opts.status,
                "actor": opts.actor,
            }, ok=(rc == 0), exit_code=rc)

        rc = status_update(
            contract_file,
            task_id=opts.task_id,
            status=opts.status,
            actor=opts.actor,
            reason=opts.reason or "",
            summary=opts.summary or "",
        )
        # Sync inbox after status update
        _sync_inbox_after_status(project_dir, opts.task_id, opts.status)
        sys.exit(rc)

    elif opts.subcmd == "set-owner":
        rc = set_owner(contract_file, opts.task_id, opts.owner)
        sys.exit(rc)


def _sync_inbox_after_status(project_dir: str, task_id: str, status: str) -> None:
    """Mirror inbox sync logic from task.sh: sync inbox when task reaches terminal state."""
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    if not os.path.exists(inbox_file):
        return
    if status not in ("done", "failed", "stopped"):
        return
    import subprocess
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "superharness.engine.inbox", "sync_task_status",
             "--file", inbox_file, "--task", task_id, "--to", status, "--now", now],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                f"Warning: failed to sync inbox task status for '{task_id}': {result.stdout.strip()} {result.stderr.strip()}",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"Warning: failed to sync inbox task status for '{task_id}': {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
