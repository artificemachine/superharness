"""Python port of task.sh — create/delete/status operations on contract tasks.

Output format is byte-for-byte identical to the Ruby version.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from typing import Optional

try:
    from ruamel.yaml import YAML as RuamelYAML
    _rt = RuamelYAML()
    _rt.preserve_quotes = True
    _rt.default_flow_style = False
    _RT_AVAILABLE = True
except ImportError:
    _RT_AVAILABLE = False

import yaml
from superharness.engine.taxonomy import VALID_EFFORTS

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

VALID_OWNERS = {"claude-code", "codex-cli"}
VALID_CREATE_STATUSES = {"todo", "in_progress", "pending_user_approval", "done"}
VALID_ALL_STATUSES = {
    "todo", "plan_proposed", "plan_approved",
    "in_progress", "report_ready",
    "review_passed", "review_failed",
    "pending_user_approval",
    "done", "failed", "stopped",
    # Soft-deleted done tasks; hidden from `shux contract` by default.
    "archived",
}
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

def _load_contract(path: str) -> object:
    """Load contract.yaml in round-trip mode (ruamel) or plain yaml."""
    if not os.path.exists(path):
        _abort(f"Missing contract file: {path}")
    if _RT_AVAILABLE:
        rt = RuamelYAML()
        rt.preserve_quotes = True
        with open(path, "r") as f:
            doc = rt.load(f)
        if doc is None:
            doc = {}
        return doc
    else:
        with open(path, "r") as f:
            doc = yaml.safe_load(f)
        if doc is None:
            doc = {}
        return doc


def _write_contract(path: str, doc: object) -> None:
    """Atomically write contract.yaml."""
    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            if _RT_AVAILABLE:
                rt = RuamelYAML()
                rt.preserve_quotes = True
                rt.default_flow_style = False
                rt.dump(doc, f)
            else:
                f.write(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
        _abort("owner must be claude-code or codex-cli", 2)
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

    doc = _load_contract(contract_file)
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

    if _RT_AVAILABLE:
        from ruamel.yaml.comments import CommentedMap
        task: dict = CommentedMap()
    else:
        task = {}

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
    doc = _load_contract(contract_file)
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

    doc = _load_contract(contract_file)
    tasks = _get_tasks(doc, contract_file)

    before = len(tasks)
    new_tasks = [t for t in tasks if not (isinstance(t, dict) and str(t.get("id", "")) == task_id)]
    if len(new_tasks) == before:
        _abort(f"task '{task_id}' not found")

    doc["tasks"] = new_tasks  # type: ignore[index]
    _write_contract(contract_file, doc)
    print(f"Deleted task '{task_id}'")
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

    if status not in VALID_ALL_STATUSES:
        _abort(f"status must be one of: {', '.join(sorted(VALID_ALL_STATUSES))}", 2)

    if status in ("failed", "stopped") and not reason:
        _abort(f"error: --reason is required when status={status}", 2)

    if status in ("todo", "in_progress", "pending_user_approval", "done") and not summary:
        _abort(f"error: --summary is required when status={status}", 2)

    doc = _load_contract(contract_file)
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
        if dep_status != "done":
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
    if status == "plan_proposed" and not _recursion_guard:
        task_autonomy = str(task.get("autonomy") or "ai_driven")
        if task_autonomy == "ai_driven":
            print(f"Auto-approving task '{task_id}' (autonomy=ai_driven)")
            status_update(
                contract_file, task_id, "plan_approved",
                actor="ai-autonomy",
                summary="auto-approved per task autonomy setting",
                _recursion_guard=True,
            )

    # Warn about unverified acceptance criteria when marking done
    if status == "done":
        ac = task.get("acceptance_criteria")
        if ac and isinstance(ac, list) and ac:
            print(f"Warning: task '{task_id}' has acceptance criteria — verify before closing:", file=sys.stderr)
            for c in ac:
                print(f"  - {c}", file=sys.stderr)

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
    _valid_status_hint = "{" + "|".join(sorted(VALID_ALL_STATUSES)) + "}"
    p_status.add_argument("--status", required=True, metavar=_valid_status_hint,
                          help=f"Lifecycle status. One of: {', '.join(sorted(VALID_ALL_STATUSES))}")
    p_status.add_argument("--actor", required=True)
    p_status.add_argument("--reason", default="")
    p_status.add_argument("--summary", default="")
    p_status.add_argument("--json", action="store_true", default=False,
                          help="Emit machine-readable JSON on stdout instead of human text.")

    opts = parser.parse_args(argv)
    if not opts.subcmd:
        parser.print_help(sys.stderr)
        sys.exit(2)

    project_dir = opts.project or os.getcwd()
    if not os.path.isabs(project_dir):
        project_dir = os.path.realpath(project_dir)
    else:
        project_dir = os.path.realpath(project_dir)

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
                    sys.stderr.write("Task owner (claude-code|codex-cli): ")
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
                _doc = _load_contract(contract_file)
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
