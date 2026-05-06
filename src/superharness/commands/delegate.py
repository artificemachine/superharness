"""Python port of delegate.sh.

Builds a prompt for the target agent (claude-code or codex-cli) and either
prints it (--print-only) or launches the CLI or SDK.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from superharness.engine.sdk_runner import sdk_available, SDKRunner
from superharness.engine.orchestrator import Orchestrator, DecompositionResult
from superharness.engine.taxonomy import VALID_EFFORTS
from superharness.engine.contract_io import read_contract as _read_contract


_JSON_MODE = False
_JSON_CTX: dict = {}


def _abort(msg: str, code: int = 1) -> None:
    if _JSON_MODE:
        from superharness.utils.json_output import emit_error
        emit_error(msg, exit_code=code, **_JSON_CTX)
    print(msg, file=sys.stderr)
    sys.exit(code)


def _build_context_hint(project_dir: str, task: dict) -> str:
    """Build a compact context block from task metadata to reduce agent cold-start.

    Scans acceptance criteria and TDD block for keywords, finds matching source
    files, and returns a pre-built context string the agent can use immediately.
    """
    lines: list[str] = []

    # Extract keywords from acceptance criteria + TDD
    keywords: list[str] = []
    for ac in task.get("acceptance_criteria") or []:
        # Pull nouns/identifiers from criteria
        for word in re.findall(r'[a-z_]{4,}', str(ac).lower()):
            if word not in ("that", "this", "with", "from", "have", "been", "should", "must", "when", "each", "into"):
                keywords.append(word)
    tdd = task.get("tdd") or {}
    for phase in ("red", "green", "refactor"):
        for word in re.findall(r'[a-z_]{4,}', str(tdd.get(phase, "")).lower()):
            if word not in ("that", "this", "with", "from", "have", "been", "should", "must", "when", "each", "into", "test", "tests", "code", "make", "pass"):
                keywords.append(word)

    # Deduplicate, take top 10
    seen_kw = set()
    unique_kw = []
    for kw in keywords:
        if kw not in seen_kw:
            seen_kw.add(kw)
            unique_kw.append(kw)
    top_keywords = unique_kw[:10]

    # 1. Keywords & Source Files
    if top_keywords:
        src_dir = os.path.join(project_dir, "src")
        if not os.path.isdir(src_dir):
            src_dir = project_dir

        relevant_files: set[str] = set()
        for kw in top_keywords[:5]:  # limit to 5 greps
            try:
                r = subprocess.run(
                    ["grep", "-rl", "--include=*.py", "-m", "3", kw, src_dir],
                    capture_output=True, text=True, check=False, timeout=5,
                )
                for f in r.stdout.strip().splitlines()[:3]:
                    if f:
                        relevant_files.add(os.path.relpath(f, project_dir))
            except Exception:
                pass

        if relevant_files:
            lines.append("\nRelevant source files (start here, don't explore from scratch):")
            for f in sorted(relevant_files)[:10]:
                lines.append(f"  - {f}")

    # 2. Recent git changes
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~3"],
            capture_output=True, text=True, check=False, timeout=5,
            cwd=project_dir,
        )
        recent = [f for f in r.stdout.strip().splitlines() if f.endswith(".py")][:5]
        if recent:
            lines.append("\nRecently changed files:")
            for f in recent:
                lines.append(f"  - {f}")
    except Exception:
        pass

    # 3. Past skill hints
    try:
        from superharness.engine.skill_extractor import get_skill_hints
        skill_hints = get_skill_hints(project_dir, task)
        if skill_hints:
            lines.append("\nRelated past skills (reuse proven approaches):")
            for h in skill_hints:
                lines.append(f"  - {h}")
    except Exception:
        pass

    # 4. Failure pattern hints & System health (Self-healing)
    task_id = str(task.get("id", ""))
    if task_id:
        try:
            from superharness.engine.failure_patterns import get_failure_hints
            hints = get_failure_hints(project_dir, task_id)
            if hints:
                lines.append("\nPrior failure hints (avoid repeating these mistakes):")
                for h in hints:
                    lines.append(f"  - {h}")
                
                # Injection of system health context
                try:
                    from superharness.commands.doctor import get_doctor_summary
                    health = get_doctor_summary(project_dir)
                    if health:
                        lines.append("\nCurrent system health (check for environmental blockers):")
                        lines.append(health)
                except Exception:
                    pass
        except Exception:
            pass

    return "\n".join(lines) if lines else ""


def _rotate_launcher_logs(log_dir: Path, task_id: str, agent: str, keep: int = 5) -> None:
    """Keep only the most recent N log files for a given task+agent combination.

    Args:
        log_dir: Directory containing launcher log files
        task_id: Task ID to filter logs
        agent: Agent name to filter logs
        keep: Number of most recent logs to keep (default: 5)
    """
    pattern = f"{task_id}-{agent}-*.log"
    log_files = sorted(log_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

    # Delete all but the most recent `keep` files
    for old_log in log_files[keep:]:
        try:
            old_log.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _read_profile_field(project_dir: str, field: str, default: str) -> str:
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.isfile(profile_file):
        return default
    try:
        import yaml
        with open(profile_file) as f:
            doc = yaml.safe_load(f) or {}
        val = doc.get(field)
        return str(val) if val is not None else default
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Contract helpers (direct YAML reads — avoids subprocess for simple fields)
# ---------------------------------------------------------------------------

def _get_contract_id(contract_file: str) -> str:
    doc, _ = _read_contract(contract_file)
    return str((doc or {}).get("id") or "") or "unknown-contract"


def _get_task_acceptance_criteria(contract_file: str, task_id: str) -> list[str]:
    doc, _ = _read_contract(contract_file)
    tasks = (doc or {}).get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            ac = t.get("acceptance_criteria")
            if isinstance(ac, list):
                return [str(c) for c in ac]
            return []
    return []


def _get_task_title(contract_file: str, task_id: str) -> str:
    doc, _ = _read_contract(contract_file)
    tasks = (doc or {}).get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            return str(t.get("title", ""))
    return ""


def _get_task_field(contract_file: str, task_id: str, field: str) -> str | None:
    """Return a string field from a task, or None if absent."""
    doc, _ = _read_contract(contract_file)
    tasks = (doc or {}).get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            val = t.get(field)
            return str(val) if val is not None else None
    return None


# Effort → max budget USD (per-task caps to prevent runaway spend)
EFFORT_BUDGET_MAP = {
    "low": 0.50,
    "medium": 2.00,
    "high": 5.00,
    "max": 15.00,
}


def _get_task_budget(contract_file: str, task_id: str, effort: str) -> float | None:
    """Return task budget: explicit budget_usd from contract, or effort-based default."""
    explicit = _get_task_field(contract_file, task_id, "budget_usd")
    if explicit:
        try:
            return float(explicit)
        except (ValueError, TypeError):
            pass
    return EFFORT_BUDGET_MAP.get(effort)


def _save_context_snapshot(project_dir: str, task_id: str, result: dict) -> None:
    """Save a context snapshot after dispatch for future warm-start reference."""
    import subprocess
    snapshot_dir = os.path.join(project_dir, ".superharness", "context-cache")
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot = {
        "task_id": task_id,
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
        "cost_usd": result.get("cost_usd", 0),
    }
    # Capture which files were modified during dispatch
    try:
        r = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, check=False, timeout=5,
            cwd=project_dir,
        )
        snapshot["files_touched"] = [f for f in r.stdout.strip().splitlines() if f]
    except Exception:
        snapshot["files_touched"] = []
    try:
        from superharness.engine.yaml_helpers import safe_dump
        with open(os.path.join(snapshot_dir, f"{task_id}.yaml"), "w") as f:
            safe_dump(snapshot, f)
    except Exception:
        pass


def _get_task_previously_failed(contract_file: str, task_id: str) -> bool:
    status = _get_task_field(contract_file, task_id, "status")
    return status == "failed"


def _get_latest_handoff_task(handoff_dir: str, to: str) -> tuple[str, str]:
    """Returns (task_id, handoff_file) or ("", "")."""
    import glob as _glob
    import yaml

    files = sorted(
        _glob.glob(os.path.join(handoff_dir, "*.yaml")),
        key=os.path.getmtime,
        reverse=True,
    )
    for fpath in files:
        try:
            with open(fpath) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            _abort(f"Failed to parse handoff {fpath}: {e}")
        if str(data.get("to", "")) != str(to):
            continue
        task_val = str(data.get("task", ""))
        if task_val:
            return task_val, fpath
    return "", ""


# ---------------------------------------------------------------------------
# Discussion round context helpers
# ---------------------------------------------------------------------------

# Thin re-exports so existing call sites in this module and any external
# imports keep working. Canonical implementations live in engine.next_action.
from superharness.engine.next_action import (  # noqa: E402
    _DISC_ROUND_RE,
    infer_workflow as _infer_workflow,
    allowed_statuses_for_workflow as _allowed_statuses_for_workflow,
    plan_only_allowed_statuses as _plan_only_allowed_statuses,
)

# Exit-code contract for permanent-block launcher failures.
# Callers (launcher / inbox dispatch) treat exit 2 as non-retryable so the
# inbox doesn't waste its retry budget on a lifecycle violation that will
# fail identically every time.
EXIT_PERMANENT_BLOCK = 2


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------

def _write_subtasks_to_contract(
    contract_file: str,
    task_id: str,
    decomposition: DecompositionResult,
) -> None:
    """Write orchestrator decomposition subtasks into contract.yaml.

    Normalises each subtask with explicit defaults (status, owner) so YAML
    matches what SQLite will store — prevents F6 mismatched drift after sync.
    """
    import yaml

    with open(contract_file) as f:
        doc = yaml.safe_load(f) or {}

    normalised: list[dict] = []
    for st in decomposition.subtasks:
        if not isinstance(st, dict):
            continue
        st = dict(st)
        st.setdefault("status", "pending")
        st.setdefault("owner", "claude-code")
        normalised.append(st)

    tasks = doc.get("tasks") or []
    for t in tasks:
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            t["subtasks"] = normalised
            t["estimated_cost_usd"] = round(decomposition.total_estimated_cost_usd, 4)
            t["budget_usd"] = round(decomposition.recommended_budget_usd, 4)
            break

    with open(contract_file, "w") as f:
        yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)


def _sqlite_mirror_orchestrate(
    project_dir: str,
    task_id: str,
    subtasks: list[dict],
) -> None:
    """Record orchestration event + upsert subtasks to SQLite. Never raises."""
    try:
        from datetime import datetime, timezone
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import tasks_dao, ledger_dao
        from superharness.engine.tasks_dao import TaskRow
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            with transaction(conn):
                ledger_dao.record(
                    conn, task_id=task_id, agent="orchestrator",
                    action="decompose",
                    details={"subtask_count": len(subtasks)},
                    now=now,
                )
                for st in subtasks:
                    st_id = str(st.get("id", ""))
                    if not st_id:
                        continue
                    # Default status="pending" matches Subtask schema and YAML normalisation
                    # in _write_subtasks_to_contract — keeps parity hash aligned (F6).
                    row = TaskRow(
                        id=st_id,
                        title=str(st.get("title", st_id)),
                        owner=str(st.get("owner", "claude-code")),
                        status=str(st.get("status") or "pending"),
                        effort=st.get("effort"),
                        project_path=project_dir,
                        development_method=None,
                        acceptance_criteria=[],
                        test_types=[],
                        out_of_scope=[],
                        definition_of_done=[],
                        context=None,
                        tdd=None,
                        version=1,
                        created_at=now,
                        blocked_by=list(st.get("blocked_by") or []),
                    )
                    tasks_dao.upsert(conn, row)
        finally:
            conn.close()
    except Exception:
        pass


def _get_round_context(disc_dir: str, round_: int, agent: str) -> dict:
    result = subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion",
         "round_context",
         "--discussion-dir", disc_dir,
         "--round", str(round_),
         "--agent", agent],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        _abort("Failed to get discussion context")
    import json
    return json.loads(result.stdout)


def _build_prior_context(ctx: dict) -> str:
    lines = []
    for r in ctx.get("prior_rounds") or []:
        lines.append(f"--- Round {r['round']} ---")
        for p in r.get("positions") or []:
            lines.append(f"Agent: {p.get('agent', '')}")
            lines.append(f"Verdict: {p.get('verdict', '')}")
            lines.append(f"Position: {p.get('position', '')}")
            pts = p.get("points") or []
            if isinstance(pts, list) and pts:
                lines.append("Points:")
                for pt in pts:
                    if isinstance(pt, dict):
                        lines.append(f"  - {pt.get('id', '')}: {pt.get('verdict', '')} — {pt.get('rationale', '')}")
            lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Confirmation helpers (mirrors Bash confirm_* functions)
# ---------------------------------------------------------------------------

def _confirm_non_interactive_risk(target: str, codex_bypass: bool) -> None:
    if target == "codex-cli" and codex_bypass:
        risk_msg = "Risk: non-interactive Codex bypass disables sandbox and approval prompts. Continue?"
    else:
        risk_msg = "Risk: non-interactive mode runs without live user supervision. Continue?"

    env_val = os.environ.get("SUPERHARNESS_CONFIRM_NON_INTERACTIVE", "")
    if env_val in ("YES", "yes", "Y", "y"):
        return

    if not sys.stdin.isatty():
        print("Refusing non-interactive launch without explicit confirmation.", file=sys.stderr)
        print("Set SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES to allow unattended launch.", file=sys.stderr)
        sys.exit(1)

    sys.stderr.write(f"{risk_msg} [y/N]: ")
    sys.stderr.flush()
    ans = sys.stdin.readline().strip()
    if ans not in ("y", "Y", "yes", "YES"):
        print("Aborted by user.", file=sys.stderr)
        sys.exit(1)


def _confirm_dangerous_flag_risk(env_name: str, risk_msg: str) -> None:
    env_val = os.environ.get(env_name, "")
    if env_val in ("YES", "yes", "Y", "y"):
        return

    if not sys.stdin.isatty():
        print("Refusing dangerous launch without explicit confirmation.", file=sys.stderr)
        print(f"Set {env_name}=YES to allow this specific bypass.", file=sys.stderr)
        sys.exit(1)

    sys.stderr.write(f"{risk_msg} [y/N]: ")
    sys.stderr.flush()
    ans = sys.stdin.readline().strip()
    if ans not in ("y", "Y", "yes", "YES"):
        print("Aborted by user.", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------

def _launch_agent(
    target: str,
    prompt: str,
    project_dir: str,
    non_interactive: bool,
    codex_bypass: bool,
    label: str = "",
    model: str = "",
    effort: str = "",
) -> None:
    display_label = f" {label}" if label else ""

    from superharness.engine.platform_runtime import launch_agent, expand_agent_path
    expand_agent_path()

    if target == "claude-code":
        if not _cmd_exists("claude"):
            _abort("claude CLI is not installed or not on PATH")
        print()

        model_args: list[str] = []
        if model:
            model_args += ["--model", model]
        if effort:
            model_args += ["--effort", effort]

        if non_interactive:
            _confirm_dangerous_flag_risk(
                "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS",
                "Risk: Claude --dangerously-skip-permissions disables permission prompts. Continue?",
            )
            print(f"Launching Claude{display_label}...")
            rc = launch_agent(
                ["claude", "-p", "--dangerously-skip-permissions"] + model_args + [prompt],
                cwd=project_dir,
            )
            sys.exit(rc)
        print(f"Launching Claude{display_label}...")
        rc = launch_agent(["claude"] + model_args + [prompt], cwd=project_dir)
        sys.exit(rc)

    elif target == "gemini-cli":
        gemini_script = str(Path(__file__).parent.parent / "scripts" / "delegate-to-gemini.sh")
        gemini_args: list[str] = ["bash", gemini_script, "--project", project_dir, "--prompt", prompt]
        if non_interactive:
            gemini_args.append("--non-interactive")
        print(f"Launching Gemini{display_label}...")
        rc = launch_agent(gemini_args, cwd=project_dir)
        sys.exit(rc)

    else:  # codex-cli
        if not _cmd_exists("codex"):
            _abort("codex CLI is not installed or not on PATH")
        print()

        codex_model_args: list[str] = []
        if model:
            codex_model_args += ["--model", model]

        if non_interactive:
            print(f"Launching Codex{display_label}...")
            common = ["exec", "--skip-git-repo-check", "-C", project_dir]
            if codex_bypass:
                _confirm_dangerous_flag_risk(
                    "SUPERHARNESS_CONFIRM_CODEX_BYPASS",
                    "Risk: Codex bypass disables sandbox and approval prompts. Continue?",
                )
                rc = launch_agent(
                    ["codex"] + common + codex_model_args + ["--dangerously-bypass-approvals-and-sandbox", prompt],
                    cwd=project_dir,
                )
                sys.exit(rc)
            rc = launch_agent(
                ["codex"] + common + codex_model_args + ["--full-auto", prompt],
                cwd=project_dir,
            )
            sys.exit(rc)
        print(f"Launching Codex{display_label}...")
        rc = launch_agent(["codex", "-C", project_dir] + codex_model_args + [prompt], cwd=project_dir)
        sys.exit(rc)


def _expand_path() -> None:
    """Augment PATH with common user-local bin dirs — launchd starts with a minimal PATH."""
    extra = [
        os.path.expanduser("~/.local/bin"),
        "/usr/local/bin",
        "/opt/homebrew/bin",
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ]
    current = os.environ.get("PATH", "")
    additions = [p for p in extra if p not in current.split(os.pathsep) and os.path.isdir(p)]
    if additions:
        os.environ["PATH"] = current + os.pathsep + os.pathsep.join(additions)


def _cmd_exists(name: str) -> bool:
    import shutil
    _expand_path()
    return shutil.which(name) is not None


# ---------------------------------------------------------------------------
# Main delegate logic
# ---------------------------------------------------------------------------

def delegate(
    project_dir: str,
    target: str,
    task_id: str,
    print_only: bool,
    non_interactive: bool,
    codex_bypass: bool,
    for_review: bool = False,
    model_override: str = "",
    effort_override: str = "",
    no_auto_model: bool = False,
    via_sdk: bool | None = None,
    orchestrate: bool = False,
    skip_preflight: bool = False,
    force: bool = False,
    plan_only: bool = False,
    ship_on_complete: bool = False,
) -> int:
    project_dir = os.path.realpath(project_dir)

    harness_dir = os.path.join(project_dir, ".superharness")
    contract_file = os.path.join(harness_dir, "contract.yaml")
    handoff_dir = os.path.join(harness_dir, "handoffs")

    if not os.path.isfile(contract_file):
        _abort(f"Missing contract file: {contract_file}")
    if not os.path.isdir(handoff_dir):
        _abort(f"Missing handoff directory: {handoff_dir}")

    contract_id = _get_contract_id(contract_file)

    latest_handoff = ""
    if not task_id:
        task_id, latest_handoff = _get_latest_handoff_task(handoff_dir, target)
        if not task_id:
            print(
                f"Could not determine task id. Provide --task TASK_ID or create a "  # shipguard:ignore PY-007
                f"{target} handoff in {handoff_dir}",
                file=sys.stderr,
            )
            return 1

    from datetime import datetime, date as _date
    today = _date.today()

    # Gate 1: scheduled_after — can't delegate before this date
    scheduled_after = _get_task_field(contract_file, task_id, "scheduled_after")
    if scheduled_after:
        try:
            sched_date = datetime.strptime(scheduled_after.strip(), "%Y-%m-%d").date()
            if today < sched_date:
                days_left = (sched_date - today).days
                print(
                    f"⛔ Task '{task_id}' is not ready — scheduled after {scheduled_after} ({days_left} day(s) from now).",
                    file=sys.stderr,
                )
                return 1
        except ValueError:
            pass

    # Gate 2: due_by — warn if past due date (don't block, just warn)
    due_by = _get_task_field(contract_file, task_id, "due_by")
    if due_by:
        try:
            due_date = datetime.strptime(due_by.strip(), "%Y-%m-%d").date()
            if today > due_date:
                days_overdue = (today - due_date).days
                print(
                    f"⚠️  Task '{task_id}' is overdue — due by {due_by} ({days_overdue} day(s) ago).",
                    file=sys.stderr,
                )
        except ValueError:
            pass

    # Gate 3: depends_on / blocked_by — block if dependency tasks are not done
    doc, _ = _read_contract(contract_file)
    task_obj = next((t for t in ((doc or {}).get("tasks") or []) if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)

    # Collect blocker IDs from both blocked_by (new) and depends_on (legacy)
    _blocked_by_val = task_obj.get("blocked_by") if task_obj else None
    _depends_on_val = task_obj.get("depends_on") if task_obj else None
    _dep_id_set: list[str] = []
    for _val in (_blocked_by_val, _depends_on_val):
        if not _val or _val == "none":
            continue
        if isinstance(_val, list):
            _dep_id_set.extend(str(d).strip() for d in _val if d and str(d).strip() != "none")
        else:
            _dep_id_set.extend(d.strip() for d in str(_val).strip("[]").split(",") if d.strip() and d.strip() != "none")

    if _dep_id_set:
        blockers = []
        for dep_id in _dep_id_set:
            dep_status = _get_task_field(contract_file, dep_id, "status")
            if dep_status not in ("done", "archived"):
                blockers.append(f"{dep_id} (status: {dep_status or 'not found'})")
        if blockers:
            print(
                f"blocked: task '{task_id}' depends on unfinished tasks:",
                file=sys.stderr,
            )
            for b in blockers:
                print(f"   - {b}", file=sys.stderr)
            return 1

    # Gate 4: status lifecycle — dispatch is workflow-aware.
    # Terminal statuses (done/failed/stopped) pass through — reconcile handles them.
    # --plan-only: relax the allowed set so the agent can propose a plan on a
    # todo/implementation task without first needing plan_approved.
    _task_status = task_obj.get("status", "") if task_obj else ""
    _workflow = _infer_workflow(task_id, task_obj)
    _DISPATCH_TERMINAL_STATUSES = {"done", "failed", "stopped"}
    if plan_only:
        _DISPATCH_ALLOWED_STATUSES = _plan_only_allowed_statuses(_workflow)
    else:
        _DISPATCH_ALLOWED_STATUSES = _allowed_statuses_for_workflow(_workflow, for_review=for_review)
    if _task_status not in _DISPATCH_ALLOWED_STATUSES and _task_status not in _DISPATCH_TERMINAL_STATUSES:
        if _workflow == "implementation":
            print(
                f"blocked: task '{task_id}' status is '{_task_status}' — "
                f"plan must be approved before delegating "
                f"(run: shux task status --id {task_id} --status plan_proposed, "
                f"or re-dispatch with --plan-only to let the agent propose the plan)",
                file=sys.stderr,
            )
        else:
            allowed = ", ".join(sorted(_DISPATCH_ALLOWED_STATUSES))
            print(
                f"blocked: task '{task_id}' status is '{_task_status}' for workflow '{_workflow}' "
                f"(allowed: {allowed})",
                file=sys.stderr,
            )
        # Permanent lifecycle block — non-retryable.
        return EXIT_PERMANENT_BLOCK

    # -----------------------------------------------------------------------
    # Pre-flight analysis (fast, local-only)
    # Runs after all gates so task_obj is resolved. Warns or blocks if needed.
    # -----------------------------------------------------------------------
    if not print_only and not skip_preflight and task_obj is not None:
        try:
            from superharness.engine.preflight import run_preflight
            pf = run_preflight(
                project_dir=project_dir,
                task=dict(task_obj),
                contract_file=contract_file,
                skip_git=non_interactive,  # skip git check in non-interactive mode
            )
            if pf.status != "pass":
                print(pf.format_summary(verbose=False), file=sys.stderr)
            if not pf.can_dispatch:
                return 1
            # Surface fanout hint if complexity suggests parallel
            if pf.suggested_mode != "single":
                print(
                    f"  Hint: consider `--fanout {pf.suggested_fanout_n}` or swarm mode for this task.",
                    file=sys.stderr,
                )
        except Exception:
            pass  # Preflight is advisory — never block on its own errors

    # -----------------------------------------------------------------------
    # Model / effort resolution
    # Order: CLI flag > task field > classifier > profile default > standard/medium
    # -----------------------------------------------------------------------
    resolved_model = ""
    resolved_effort = ""
    model_source = "fallback"

    # 1. CLI flag
    if model_override:
        resolved_model = model_override
        model_source = "manual"
    if effort_override:
        resolved_effort = effort_override

    # 2. Task field (if not already set by CLI)
    if not resolved_model:
        task_model = _get_task_field(contract_file, task_id, "model")
        if task_model:
            resolved_model = task_model
            model_source = "task"
    if not resolved_effort:
        task_effort = _get_task_field(contract_file, task_id, "effort")
        if task_effort:
            resolved_effort = task_effort

    # 3. Auto-classification (if not fully resolved and not disabled)
    if not no_auto_model and (not resolved_model or not resolved_effort):
        try:
            from superharness.engine.adapter_registry import (
                clear_manifest_cache,
                resolve_model as _resolve_model,
            )
            from superharness.engine.model_router import classify_task, resolve_tier
            
            # Force reload of manifests (prevents stale "sonnet" fallback)
            clear_manifest_cache()

            task_title = _get_task_title(contract_file, task_id)
            ac_for_classify = _get_task_acceptance_criteria(contract_file, task_id)
            previously_failed = _get_task_previously_failed(contract_file, task_id)

            classified_tier, classified_effort = classify_task(
                title=task_title or task_id,
                criteria=ac_for_classify or None,
                previously_failed=previously_failed,
            )
            if not resolved_model:
                _m = _resolve_model(target, classified_tier)
                resolved_model = _m.get("id", classified_tier) if isinstance(_m, dict) else _m
                model_source = "auto-classified"
            if not resolved_effort:
                resolved_effort = classified_effort
        except Exception:
            pass  # classification failure is non-fatal

    # 4. Profile defaults
    if not resolved_model:
        profile_model = _read_profile_field(project_dir, "default_model", "")
        if profile_model:
            try:
                from superharness.engine.model_router import resolve_model as _resolve_model, resolve_tier
                tier = resolve_tier(profile_model)
                if tier:
                    resolved_model = _resolve_model(target, tier)
                else:
                    resolved_model = profile_model
            except Exception:
                resolved_model = profile_model
            model_source = "profile"
    if not resolved_effort:
        profile_effort = _read_profile_field(project_dir, "default_effort", "")
        if profile_effort:
            resolved_effort = profile_effort

    # 5. Hardcoded fallback
    if not resolved_model:
        try:
            from superharness.engine.model_router import resolve_model as _resolve_model
            resolved_model = _resolve_model(target, "standard")
        except Exception:
            resolved_model = "sonnet"
        model_source = "fallback"
    if not resolved_effort:
        resolved_effort = "medium"

    # If model_override was a tier name, resolve to agent-specific model
    try:
        from superharness.engine.model_router import resolve_tier, resolve_model as _resolve_model
        tier = resolve_tier(resolved_model)
        if tier:
            resolved_model = _resolve_model(target, tier)
    except Exception:
        pass

    # -----------------------------------------------------------------------
    # Orchestrator mode: decompose task into subtasks before dispatch
    # -----------------------------------------------------------------------
    if orchestrate and target in ("claude-code", "codex-cli"):
        orch = Orchestrator(project_dir=project_dir)
        task_data = {
            "id": task_id,
            "title": _get_task_title(contract_file, task_id) or task_id,
            "owner": target,
            "acceptance_criteria": _get_task_acceptance_criteria(contract_file, task_id),
        }
        decomposition = orch.decompose(task_data)

        # Write subtasks to contract + mirror to SQLite
        _write_subtasks_to_contract(contract_file, task_id, decomposition)
        _sqlite_mirror_orchestrate(project_dir, task_id, decomposition.subtasks)

        # Print decomposition summary
        print()
        print(f"Orchestrator decomposition for {task_id}:")
        print(f"  Subtasks: {len(decomposition.subtasks)}")
        for st in decomposition.subtasks:
            print(f"    - {st['id']}: {st['title']} [{st['model_tier']}] ~{st.get('estimated_tokens', 0)} tokens")
        print(f"  Estimated cost: ${decomposition.total_estimated_cost_usd:.4f}")
        print(f"  Recommended budget: ${decomposition.recommended_budget_usd:.4f}")

        if print_only:
            return 0

    # Acceptance criteria
    ac_lines = _get_task_acceptance_criteria(contract_file, task_id)
    acceptance_criteria = ""
    if ac_lines:
        ac_block = "\n".join(f"- {c}" for c in ac_lines)
        acceptance_criteria = f"\n\nAcceptance criteria for this task:\n{ac_block}"

    auto_directive = ""
    if non_interactive:
        auto_directive = (
            "\nThis is an automated non-interactive run. "
            "Do not ask for confirmation or approval. "
            "Proceed and apply all changes immediately."
        )

    if plan_only:
        # Plan-only dispatch: agent must write a plan handoff and stop. No
        # implementation code should be touched on this turn. The owner will
        # review the plan and re-dispatch (without --plan-only) to execute.
        auto_directive += (
            "\n\n=== PLAN-ONLY MODE ===\n"
            f"Your only job on this turn is to propose a TDD plan for task '{task_id}'.\n"
            "1. Do NOT write, modify, or delete any source, test, or configuration file.\n"
            "2. Write a plan handoff YAML to .superharness/handoffs/ with:\n"
            f"   task: {task_id}\n"
            "   phase: plan\n"
            "   status: plan_proposed\n"
            f"   from: {target}\n"
            "   to: owner\n"
            "   date: <ISO-8601 UTC timestamp>\n"
            "   plan: <scope and approach — 1–3 short paragraphs>\n"
            "   tdd:\n"
            "     red: <the failing tests you will add first — specific names/locations>\n"
            "     green: <the minimal implementation that will make them pass>\n"
            "     refactor: <cleanup planned after green, or 'none'>\n"
            "   risks: <open questions, unknowns, dependencies>\n"
            "3. Run `shux task status --id " + task_id + " --status plan_proposed` to transition the task.\n"
            "4. Stop. Do not proceed to implementation. The owner must review and approve the plan first.\n"
        )

    # ship_on_complete: inject directive so the agent runs /ship commit before report_ready
    _ship_on_complete = ship_on_complete or str(
        _get_task_field(contract_file, task_id, "ship_on_complete") or ""
    ).lower() in ("true", "1", "yes")
    if _ship_on_complete:
        auto_directive += (
            "\n\n=== SHIP-ON-COMPLETE ===\n"
            "This task has ship_on_complete: true.\n"
            "After all acceptance criteria are met and BEFORE writing report_ready:\n"
            "1. Run `ALLOW_PUSH=1 /ship commit` (non-interactive) inside this worktree.\n"
            "2. If /ship commit exits non-zero, do NOT write report_ready.\n"
            "   Instead write a failed handoff and exit.\n"
            "3. Include the PR URL in your handoff outcomes list "
            "(e.g. 'PR: https://github.com/org/repo/pull/N').\n"
            "4. Only after /ship commit succeeds, set task status to report_ready.\n"
        )

    # Discussion-round detection
    m = _DISC_ROUND_RE.match(task_id)
    discussion_id = m.group(1) if m else ""
    discussion_round = int(m.group(2)) if m else 0

    discussions_dir = os.path.join(harness_dir, "discussions")
    prompt = ""

    if discussion_id and discussion_round:
        disc_dir = os.path.join(discussions_dir, discussion_id)
        if not os.path.isdir(disc_dir):
            _abort(f"Discussion directory not found: {disc_dir}")

        ctx = _get_round_context(disc_dir, discussion_round, target)
        disc_topic = str(ctx.get("topic") or "")
        disc_max = str(ctx.get("max_rounds") or "")
        submit_path = os.path.join(disc_dir, f"round-{discussion_round}-{target}.yaml")

        if discussion_round == 1:
            prompt = (
                f"You are participating in a multi-agent discussion.\n"
                f"Topic: {disc_topic}\n"
                f"You are: {target}\n"
                f"This is round {discussion_round} of {disc_max}.\n"
                f"\n"
                f"Review the topic and write your position. Be specific about what you agree or disagree with.\n"
                f"\n"
                f"When done, write a YAML file to: {submit_path}\n"
                f"The file must have these fields:\n"
                f"  discussion_id: {discussion_id}\n"
                f"  round: {discussion_round}\n"
                f"  agent: {target}\n"
                f"  verdict: agree OR disagree OR partial\n"
                f"  position: your free-form analysis\n"
                f"  points: list of {{id, verdict, rationale}} for each sub-point\n"
                f"  submitted_at: (current UTC ISO 8601 timestamp)\n"
                f"\n"
                f"If you agree with everything, set verdict: agree. "
                f"Otherwise set verdict: disagree or partial and explain in points.\n"
                f"Read .superharness/discussions/{discussion_id}/state.yaml for the full discussion context.\n"
                f"Read the handoff referenced in .superharness/contract.yaml for the task details."
                f"{auto_directive}"
            )
        else:
            prior_context = _build_prior_context(ctx)
            prompt = (
                f"You are participating in a multi-agent discussion.\n"
                f"Topic: {disc_topic}\n"
                f"You are: {target}\n"
                f"This is round {discussion_round} of {disc_max}.\n"
                f"\n"
                f"Here are the positions from prior rounds:\n"
                f"{prior_context}\n"
                f"\n"
                f"Consider the other agent's position carefully. "
                f"If you now agree with all points, set verdict: agree.\n"
                f"If you still disagree, explain specifically what remains unresolved.\n"
                f"\n"
                f"Write your response to: {submit_path}\n"
                f"The file must have these fields:\n"
                f"  discussion_id: {discussion_id}\n"
                f"  round: {discussion_round}\n"
                f"  agent: {target}\n"
                f"  verdict: agree OR disagree OR partial\n"
                f"  position: your free-form analysis\n"
                f"  points: list of {{id, verdict, rationale}} for each sub-point\n"
                f"  submitted_at: (current UTC ISO 8601 timestamp)\n"
                f"\n"
                f"Read .superharness/discussions/{discussion_id}/state.yaml for full context."
                f"{auto_directive}"
            )

        print(f"Project: {project_dir}")
        print(f"Discussion: {discussion_id}")
        print(f"Round: {discussion_round}")
        print(f"Agent: {target}")
        print(f"Topic: {disc_topic}")

    else:
        # Check for user-provided instructions file
        instructions_file = os.path.join(handoff_dir, f"{task_id}-instructions.md")
        user_instructions = ""
        if os.path.isfile(instructions_file):
            user_instructions = Path(instructions_file).read_text(encoding="utf-8").strip()
            if user_instructions:
                user_instructions = f"\n\nUser instructions for this task:\n{user_instructions}"

        # Build context hint to reduce cold-start exploration time
        context_hint = _build_context_hint(project_dir, task_obj or {})

        if target == "claude-code":
            if latest_handoff:
                prompt = (
                    f"continue contract\n"
                    f"Read the latest handoff addressed to claude-code and execute task {task_id}.\n"
                    f"Use scope, commands, and acceptance criteria from the handoff.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and refresh the handoff with outcomes.\n"
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{context_hint}{user_instructions}{auto_directive}"
                )
            else:
                prompt = (
                    f"continue contract\n"
                    f"No handoff exists yet for task {task_id}.\n"
                    f"Read .superharness/contract.yaml directly and execute task {task_id}.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and create a new handoff with outcomes.\n"  # shipguard:ignore PY-007
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{context_hint}{user_instructions}{auto_directive}"
                )
        elif target == "gemini-cli":
            if latest_handoff:
                prompt = (
                    f"continue contract\n"
                    f"Read the latest handoff addressed to gemini-cli and execute task {task_id}.\n"
                    f"Use scope, commands, and acceptance criteria from the handoff.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and refresh the handoff with outcomes.\n"
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{context_hint}{user_instructions}{auto_directive}"
                )
            else:
                prompt = (
                    f"continue contract\n"
                    f"No handoff exists yet for task {task_id}.\n"
                    f"Read .superharness/contract.yaml directly and execute task {task_id}.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and create a new handoff with outcomes.\n"  # shipguard:ignore PY-007
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{context_hint}{user_instructions}{auto_directive}"
                )
        else:  # codex-cli
            if latest_handoff:
                prompt = (
                    f"continue contract\n"
                    f"Read the latest handoff addressed to codex-cli and execute task {task_id}.\n"
                    f"Use scope, commands, and acceptance criteria from the handoff.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and refresh the handoff with outcomes.\n"
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{user_instructions}"
                )
            else:
                prompt = (
                    f"continue contract\n"
                    f"No handoff exists yet for task {task_id}.\n"
                    f"Read .superharness/contract.yaml directly and execute task {task_id}.\n"
                    f"Update .superharness/contract.yaml task status, append .superharness/ledger.md, "  # shipguard:ignore PY-007
                    f"and create a new handoff with outcomes.\n"  # shipguard:ignore PY-007
                    f"Contract id: {contract_id}."
                    f"{acceptance_criteria}{user_instructions}"
                )

        # Enrich prompt with vault context
        task_title = _get_task_title(contract_file, task_id)
        try:
            from superharness.engine.osm import vault_search
            vault_results = vault_search(task_title or task_id)
            if vault_results:
                vault_block = "\n\nVault notes relevant to this task (via obsidian-semantic):\n"
                for r in vault_results:
                    preview = r.get("preview", "")[:120].replace("\n", " ")
                    vault_block += f"  - {r['path']} (similarity: {r['similarity']})\n    {preview}\n"
                prompt += vault_block
        except Exception:
            pass

        print(f"Project: {project_dir}")
        print(f"Contract: {contract_id}")
        print(f"Task: {task_id}")
        if latest_handoff:
            print(f"Handoff: {latest_handoff}")

    print(f"Model: {resolved_model} ({model_source})")
    print(f"Effort: {resolved_effort}")

    # SDK vs CLI dispatch — auto-detect: use SDK if available, fall back to CLI
    # Current limit: only claude-code supports the SDK runner
    supports_sdk = (target == "claude-code")
    use_sdk = via_sdk if via_sdk is not None else (sdk_available() and supports_sdk)
    if use_sdk and not sdk_available():
        print("⚠️  SDK not available — falling back to CLI", file=sys.stderr)
        use_sdk = False

    print(f"Via: {'sdk' if use_sdk else 'cli'}")

    # Stamp model tier onto task in SQLite so reviewers know author's tier
    if not print_only:
        try:
            from superharness.engine.model_router import find_tier_for_model
            from superharness.engine.state_writer import mirror_task_dict
            from superharness.engine import state_reader as _sr
            
            tier = find_tier_for_model(target, resolved_model, project_dir)
            _task = next((t for t in _sr.get_tasks(project_dir) if str(t.get("id")) == str(task_id)), None)
            if _task and _task.get("model_tier") != tier:
                _task["model_tier"] = tier
                mirror_task_dict(project_dir, _task)
                print(f"Stamped model tier: {tier}")
        except Exception as e:
            print(f"Warning: failed to stamp model tier: {e}", file=sys.stderr)

    if print_only:
        print()
        print("Generated prompt:")
        print("-----------------")
        print(prompt)
        return 0

    # Budget guard — warn or block before any dispatch
    try:
        from superharness.engine.model_budget import check_budget, BudgetStatus
        budget_result = check_budget(project_dir)
        if budget_result.status == BudgetStatus.WARN:
            print(f"\n⚠️  {budget_result.message}")
        elif budget_result.status == BudgetStatus.BLOCK:
            print(f"\n⛔ {budget_result.message}", file=sys.stderr)
            print("  Use --force to override.", file=sys.stderr)
            if not force:
                return 1
    except Exception:
        pass  # budget check is best-effort — never block dispatch on error

    # SDK dispatch path
    if use_sdk:
        print()
        print(f"Launching via SDK (model: {resolved_model})...")
        try:
            # Use dispatcher-provided log path if available, otherwise create our own
            env_log = os.environ.get("SUPERHARNESS_LAUNCHER_LOG")
            if env_log:
                log_file = Path(env_log)
                log_file.parent.mkdir(parents=True, exist_ok=True)
            else:
                from datetime import datetime
                log_dir = Path(harness_dir) / "launcher-logs"
                log_dir.mkdir(exist_ok=True)
                timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
                log_file = log_dir / f"{task_id}-{target}-{timestamp}.log"
                _rotate_launcher_logs(log_dir, task_id, target, keep=5)

            task_budget = _get_task_budget(contract_file, task_id, resolved_effort)
            if task_budget:
                print(f"Budget: ${task_budget:.2f}")
            runner = SDKRunner(
                project_dir=Path(project_dir),
                model=resolved_model,
                max_budget_usd=task_budget,
            )
            result = runner.run(prompt, log_file=log_file)
            print()
            print("SDK execution completed:")
            print(result.get("output", ""))
            print(f"\nLauncher log: {log_file}")

            # Save context snapshot for warm-start on related future tasks
            _save_context_snapshot(project_dir, task_id, result)
            return 0
        except Exception as e:
            print(f"⚠️  SDK execution failed: {e}", file=sys.stderr)
            print("Falling back to CLI...", file=sys.stderr)
            use_sdk = False

    # CLI dispatch path (original behavior)
    if non_interactive:
        _confirm_non_interactive_risk(target, codex_bypass)

    label = f"for discussion round {discussion_round}" if discussion_id else ""
    _launch_agent(
        target, prompt, project_dir, non_interactive, codex_bypass,
        label=label, model=resolved_model, effort=resolved_effort,
    )
    return 0  # unreachable after exec, but satisfies type checker


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> "argparse.ArgumentParser":
    import argparse

    class _CapUsage(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(usage, actions, groups, "Usage: ")

    parser = argparse.ArgumentParser(
        prog="delegate",
        description="Build prompt for target agent and launch or print it",
        formatter_class=_CapUsage,
        add_help=True,
    )
    parser.add_argument("--to", required=False, dest="target", default=None,
                        help="Target agent: claude-code or codex-cli")
    parser.add_argument("--project", "-p", default=None,
                        help="Project directory (default: current directory)")
    parser.add_argument("--task", "-t", default="",
                        help="Task ID from contract.yaml (default: latest handoff for target)")
    parser.add_argument("--print-only", action="store_true", default=False,
                        help="Print the generated prompt without launching the agent")
    parser.add_argument("--non-interactive", action="store_true", default=False,
                        help="Launch agent without live supervision (requires confirmation or env var)")
    parser.add_argument("--yolo", action="store_true", default=False,
                        help="Dangerously skip permissions and apply changes without asking")
    parser.add_argument("--codex-bypass", action="store_true", default=False,
                        help="Codex only: use --dangerously-bypass-approvals-and-sandbox")
    parser.add_argument("--for-review", action="store_true", default=False,
                        help="Allow dispatch of review_requested tasks for review workflow only")
    parser.add_argument(
        "--model", default=None,
        help="Override model. Accepts tier (mini/standard/max) or model name (sonnet, gpt-5.3-codex, etc.)",
    )
    parser.add_argument(
        "--effort", default=None,
        choices=list(VALID_EFFORTS),
        help="Override thinking effort (low/medium/high)",
    )
    parser.add_argument(
        "--no-auto-model", action="store_true", default=False,
        help="Skip auto-classification, use profile defaults or standard/medium",
    )
    parser.add_argument(
        "--via", default=None,
        choices=["cli", "sdk"],
        help="Force dispatch method (default: auto-detect — SDK if installed, CLI otherwise)",
    )
    parser.add_argument(
        "--orchestrate", action="store_true", default=False,
        help="Opus orchestrator mode: decompose task into subtasks, assign model tiers, estimate cost",
    )
    parser.add_argument(
        "--skip-preflight", action="store_true", default=False,
        help="Skip pre-flight analysis (useful when you know the task is ready)",
    )
    parser.add_argument(
        "--force", action="store_true", default=False,
        help="Override budget block for this dispatch",
    )
    parser.add_argument(
        "--plan-only", action="store_true", default=False,
        dest="plan_only",
        help="Agent proposes a TDD plan and stops (no implementation). "
             "Relaxes gate 4 so todo+implementation tasks are dispatchable.",
    )
    parser.add_argument(
        "--1m-context", action="store_true", default=False,
        dest="context_1m",
        help="Force max-1m tier (claude-opus-4-7[1m]) for this dispatch. "
             "Implies effort=max. Use when prompt exceeds ~200K tokens.",
    )
    parser.add_argument(
        "--ship-on-complete", action="store_true", default=False,
        dest="ship_on_complete",
        help="Override: inject SHIP-ON-COMPLETE directive for this dispatch even "
             "if the contract task does not have ship_on_complete: true.",
    )
    parser.add_argument(
        "--json", action="store_true", default=False,
        help="Emit machine-readable JSON on stdout instead of human text. "
             "Implies --print-only when no --via is forced.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = _build_parser()
    opts = parser.parse_args(argv)

    global _JSON_MODE, _JSON_CTX
    if getattr(opts, "json", False):
        _JSON_MODE = True
        _JSON_CTX = {"task_id": opts.task, "to": opts.target}
        # --json implies --print-only so we get a deterministic exit without
        # launching an interactive agent.
        opts.print_only = True

    if opts.target is None:
        parser.error("--to is required")
    if opts.target not in ("claude-code", "codex-cli", "gemini-cli"):
        if _JSON_MODE:
            from superharness.utils.json_output import emit_error
            emit_error("--to must be one of: claude-code, codex-cli, gemini-cli", exit_code=2, **_JSON_CTX)
        print("--to must be one of: claude-code, codex-cli, gemini-cli", file=sys.stderr)
        sys.exit(2)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    if not os.path.isdir(project_dir):
        print(f"Project directory does not exist: {project_dir}", file=sys.stderr)
        sys.exit(1)

    # Apply autonomy from profile (mirrors Bash export logic)
    autonomy = _read_profile_field(project_dir, "autonomy", "approval-gated")
    if autonomy == "autonomous":
        os.environ.setdefault("SUPERHARNESS_CONFIRM_NON_INTERACTIVE", "YES")
        os.environ.setdefault("SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS", "YES")
    elif autonomy == "supervised":
        os.environ.setdefault("SUPERHARNESS_CONFIRM_NON_INTERACTIVE", "YES")

    if _JSON_MODE:
        import io
        _orig_stdout = sys.stdout
        sys.stdout = io.StringIO()
        try:
            rc = delegate(
                project_dir=project_dir,
                target=opts.target,
                task_id=opts.task,
                print_only=opts.print_only,
                non_interactive=opts.non_interactive,
                codex_bypass=opts.codex_bypass,
                for_review=opts.for_review,
                model_override=opts.model or "",
                effort_override=opts.effort or "",
                no_auto_model=opts.no_auto_model,
                via_sdk=True if opts.via == "sdk" else (False if opts.via == "cli" else None),
                orchestrate=opts.orchestrate,
                skip_preflight=opts.skip_preflight,
                force=opts.force,
                plan_only=opts.plan_only,
                ship_on_complete=opts.ship_on_complete,
            )
            captured = sys.stdout.getvalue()
        finally:
            sys.stdout = _orig_stdout
        prompt_text = ""
        if "Generated prompt:" in captured:
            prompt_text = captured.split("-----------------", 1)[-1].strip()
        from superharness.utils.json_output import emit_json
        emit_json({
            "task_id": opts.task,
            "to": opts.target,
            "print_only": bool(opts.print_only),
            "plan_only": bool(opts.plan_only),
            "orchestrate": bool(opts.orchestrate),
            "prompt": prompt_text,
            "prompt_length": len(prompt_text),
        }, ok=(rc == 0), exit_code=rc)

    rc = delegate(
        project_dir=project_dir,
        target=opts.target,
        task_id=opts.task,
        print_only=opts.print_only,
        non_interactive=opts.non_interactive,
        codex_bypass=opts.codex_bypass,
        for_review=opts.for_review,
        model_override=opts.model or "",
        effort_override=opts.effort or "",
        no_auto_model=opts.no_auto_model,
        via_sdk=True if opts.via == "sdk" else (False if opts.via == "cli" else None),
        orchestrate=opts.orchestrate,
        skip_preflight=opts.skip_preflight,
        force=opts.force,
        plan_only=opts.plan_only,
        ship_on_complete=opts.ship_on_complete,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
