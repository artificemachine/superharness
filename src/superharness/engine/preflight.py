"""Pre-flight analysis — validate a task before full dispatch.

Runs a cheap, local-only check pass before any API call is made.
Returns a PreflightReport that callers use to decide whether to proceed,
warn, or block the dispatch entirely.

Integration:
    Called from commands/delegate.py after status gates and before prompt build.
    Also available standalone: `shux preflight --task <id>`
"""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

LEVEL_INFO = "info"
LEVEL_WARN = "warn"
LEVEL_BLOCK = "block"

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_BLOCK = "block"


@dataclass
class PreflightCheck:
    id: str
    level: str       # info | warn | block
    message: str
    detail: str = ""


@dataclass
class PreflightReport:
    task_id: str
    status: str                           # pass | warn | block
    checks: list[PreflightCheck] = field(default_factory=list)
    suggested_fanout_n: int = 1           # 1 = single, >1 = parallel/swarm
    suggested_mode: str = "single"        # single | fanout | swarm
    can_dispatch: bool = True

    # Convenience views
    @property
    def blockers(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.level == LEVEL_BLOCK]

    @property
    def warnings(self) -> list[PreflightCheck]:
        return [c for c in self.checks if c.level == LEVEL_WARN]

    def format_summary(self, verbose: bool = False) -> str:
        icon = {"pass": "✓", "warn": "⚠", "block": "✗"}.get(self.status, "?")
        lines = [f"{icon} Preflight [{self.status.upper()}] task={self.task_id}"]
        if not self.can_dispatch:
            lines.append("  Dispatch aborted — resolve blockers before retrying.")
        if self.suggested_mode != "single":
            lines.append(
                f"  Suggestion: this task may benefit from parallel dispatch (n={self.suggested_fanout_n}, mode={self.suggested_mode})"
            )
        for c in self.checks:
            if verbose or c.level in (LEVEL_WARN, LEVEL_BLOCK):
                prefix = {"info": "  ·", "warn": "  ⚠", "block": "  ✗"}.get(c.level, "  ?")
                lines.append(f"{prefix} [{c.id}] {c.message}")
                if c.detail:
                    lines.append(f"      {c.detail}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_spec_complete(task: dict) -> list[PreflightCheck]:
    checks = []
    if not task.get("title"):
        checks.append(PreflightCheck(
            id="no_title", level=LEVEL_WARN,
            message="Task has no title — agent may lack context.",
        ))
    if not task.get("owner"):
        checks.append(PreflightCheck(
            id="no_owner", level=LEVEL_WARN,
            message="Task has no owner — dispatch target may be ambiguous.",
        ))
    return checks


def _check_tdd_block(task: dict) -> list[PreflightCheck]:
    tdd = task.get("tdd") or {}
    if not tdd.get("red"):
        return [PreflightCheck(
            id="no_tdd_red", level=LEVEL_WARN,
            message="No TDD red phase defined — agent will code without a failing test first.",
            detail="Add a tdd.red block describing which tests to write before implementing.",
        )]
    if not tdd.get("green"):
        return [PreflightCheck(
            id="no_tdd_green", level=LEVEL_WARN,
            message="TDD red phase exists but no green phase — incomplete TDD spec.",
        )]
    return [PreflightCheck(
        id="tdd_ok", level=LEVEL_INFO,
        message="TDD block present (red + green).",
    )]


def _check_acceptance_criteria(task: dict) -> list[PreflightCheck]:
    ac = task.get("acceptance_criteria") or []
    if not ac:
        return [PreflightCheck(
            id="no_acceptance_criteria", level=LEVEL_WARN,
            message="No acceptance criteria — agent has no clear definition of done.",
            detail="Add acceptance_criteria to the task.",
        )]
    n = len(ac)
    if n > 6:
        return [PreflightCheck(
            id="too_many_criteria", level=LEVEL_WARN,
            message=f"Task has {n} acceptance criteria — consider decomposing.",
            detail="Tasks with >6 criteria are often too large for a single dispatch.",
        )]
    return [PreflightCheck(
        id="acceptance_criteria_ok", level=LEVEL_INFO,
        message=f"{n} acceptance criteria defined.",
    )]


def _check_dependencies(task: dict, project_dir: str) -> list[PreflightCheck]:
    """Check that all blocked_by / depends_on tasks are done."""
    checks: list[PreflightCheck] = []
    blocked_by = task.get("blocked_by") or task.get("depends_on")
    if not blocked_by or blocked_by == "none":
        return checks

    dep_ids: list[str] = []
    if isinstance(blocked_by, list):
        dep_ids = [str(d).strip() for d in blocked_by if d and str(d).strip() != "none"]
    else:
        dep_ids = [d.strip() for d in str(blocked_by).strip("[]").split(",")
                   if d.strip() and d.strip() != "none"]

    if not dep_ids:
        return checks

    try:
        from superharness.engine import state_reader as _sr
        tasks = _sr.get_tasks(project_dir)
        tasks_by_id = {str(t.get("id", "")): t for t in tasks if isinstance(t, dict)}
    except Exception as e:
        logger.warning("preflight.py unexpected error: %s", e, exc_info=True)
        tasks_by_id = {}

    for dep_id in dep_ids:
        dep = tasks_by_id.get(dep_id)
        dep_status = dep.get("status", "not_found") if dep else "not_found"
        if dep_status not in ("done", "archived"):
            checks.append(PreflightCheck(
                id="blocked_dependency", level=LEVEL_BLOCK,
                message=f"Blocked by '{dep_id}' (status: {dep_status}).",
                detail="Complete the blocking task before dispatching this one.",
            ))

    return checks


# ---------------------------------------------------------------------------
# Capability requirements (`requires:` block) — skills / CLIs / MCP / env
# Mirrors OpenProse's `### Tools` gate: a task refuses to dispatch to an agent
# that is missing a declared skill, CLI, MCP server, or env precondition.
# The `requires:` block lives in the task's extras_json (SQLite source of truth)
# and is surfaced on the task dict by state_reader.get_task.
# ---------------------------------------------------------------------------

_SKILL_DIRS = [
    Path.home() / ".claude" / "skills",
    Path.home() / ".codex" / "skills",
]
_COMMAND_DIRS = [Path.home() / ".claude" / "commands"]

_MCP_LIST_CACHE: str | None = None
_MCP_LIST_DONE = False

# ---------------------------------------------------------------------------
# Signal-to-requires rules: auto-derive capability deps from task fields.
# Each entry is (test_type_substring, cli_binary_id).
# Rationale: if a task demands security testing, the security tool must be on
# PATH — the agent cannot run the test type without the binary.
# NOTE: ship_on_complete → ALLOW_PUSH is intentionally excluded: the /ship
# directive sets ALLOW_PUSH=1 internally, so requiring it at dispatch time
# would false-block every ship task.
# ---------------------------------------------------------------------------
_SIGNAL_CLI_RULES: list[tuple[str, str]] = [
    ("security", "gitleaks"),
    ("security", "shipguard"),
    ("sast", "shipguard"),
]


def _mcp_listing() -> str | None:
    """Best-effort lowercased `claude mcp list` output, cached. None if unavailable."""
    global _MCP_LIST_CACHE, _MCP_LIST_DONE
    if _MCP_LIST_DONE:
        return _MCP_LIST_CACHE
    _MCP_LIST_DONE = True
    claude = shutil.which("claude")
    if not claude:
        return None
    try:
        r = subprocess.run([claude, "mcp", "list"], capture_output=True, text=True, timeout=15)
        _MCP_LIST_CACHE = (r.stdout + r.stderr).lower()
    except Exception as e:
        logger.warning("preflight.py mcp list failed: %s", e)
        _MCP_LIST_CACHE = None
    return _MCP_LIST_CACHE


def _skill_present(sid: str) -> bool:
    for base in _SKILL_DIRS:
        if (base / sid).is_dir():
            return True
    for base in _COMMAND_DIRS:
        if (base / f"{sid}.md").is_file():
            return True
    return False


def _load_profile_requires(project_dir: str) -> dict | None:
    """Load project-level `requires:` baseline from .superharness/profile.yaml.

    Returns None if absent or malformed — callers treat None as "no baseline".
    """
    profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.exists(profile_path):
        return None
    try:
        import yaml as _yaml
        with open(profile_path) as _f:
            profile = _yaml.safe_load(_f) or {}
        req = profile.get("requires")
        return req if isinstance(req, dict) else None
    except Exception as e:
        logger.warning("preflight.py profile requires load failed: %s", e)
        return None


def _item_key(item: object) -> str:
    """Canonical string key for a requires list item (id/name/server or str)."""
    if isinstance(item, dict):
        return str(item.get("id") or item.get("name") or item.get("server") or "")
    return str(item)


def _merge_requires(base: dict | None, override: dict | None) -> dict | None:
    """Merge two requires dicts; override wins on fail_mode and de-duplication.

    Items in `base` that are absent from `override` (by key) are appended, so
    the baseline extends rather than replaces the per-task block.
    """
    if not base and not override:
        return None
    if not base:
        return override
    if not override:
        return base
    merged: dict = {}
    merged["fail_mode"] = override.get("fail_mode") or base.get("fail_mode") or "block"
    for key in ("skills", "cli", "env", "mcp"):
        b_items = list(base.get(key) or [])
        o_items = list(override.get(key) or [])
        o_ids = {_item_key(i) for i in o_items}
        combined = list(o_items)
        for item in b_items:
            if _item_key(item) not in o_ids:
                combined.append(item)
        if combined:
            merged[key] = combined
    return merged if any(merged.get(k) for k in ("skills", "cli", "env", "mcp")) else None


def _derive_signal_requires(task: dict) -> dict | None:
    """Auto-derive capability requirements from task signals (test_types etc.).

    Currently derives CLI requirements from test_types only.  The derived block
    always uses fail_mode='block' so missing security tools hard-block dispatch.
    """
    test_types = {str(t).lower() for t in (task.get("test_types") or [])}
    cli_ids: list[str] = []
    seen: set[str] = set()
    for tt, cid in _SIGNAL_CLI_RULES:
        if tt in test_types and cid not in seen:
            cli_ids.append(cid)
            seen.add(cid)
    if not cli_ids:
        return None
    return {
        "fail_mode": "block",
        "cli": [{"id": cid, "reason": "auto-derived from test_types"} for cid in cli_ids],
    }


def _check_requires(task: dict, project_dir: str | None = None) -> list[PreflightCheck]:
    """Verify a task's declared capability dependencies before dispatch.

    Merges three requires sources in priority order (lowest to highest):
    1. Project-level baseline from .superharness/profile.yaml (if project_dir given)
    2. Signal-derived requirements from task fields (test_types → CLI tools)
    3. Per-task `requires:` block from extras_json (SQLite source of truth)

    Unmet hard deps block dispatch when ``requires.fail_mode`` is ``block``
    (the default), or warn when ``warn``. MCP presence is best-effort. Tasks
    with no requires block anywhere produce no checks (fully backward compatible).
    """
    per_task = task.get("requires")
    if not isinstance(per_task, dict):
        per_task = None

    baseline = _load_profile_requires(project_dir) if project_dir else None
    signal = _derive_signal_requires(task)

    # Merge: baseline <- signal <- per_task (highest priority wins)
    req = _merge_requires(_merge_requires(baseline, signal), per_task)

    if not isinstance(req, dict) or not req:
        return []

    fail_mode = str(req.get("fail_mode") or "block").lower()
    hard_level = LEVEL_BLOCK if fail_mode == "block" else LEVEL_WARN
    checks: list[PreflightCheck] = []

    def _reason(item) -> str:
        return (item.get("reason") if isinstance(item, dict) else "") or ""

    # Skills
    for item in req.get("skills") or []:
        sid = item.get("id") if isinstance(item, dict) else str(item)
        if sid and not _skill_present(sid):
            checks.append(PreflightCheck(
                id="requires_skill_missing", level=hard_level,
                message=f"Required skill '{sid}' not found.",
                detail=_reason(item) or "Install it under ~/.claude/skills or ~/.claude/commands.",
            ))

    # CLIs
    for item in req.get("cli") or []:
        cid = item.get("id") if isinstance(item, dict) else str(item)
        if cid and shutil.which(cid) is None:
            checks.append(PreflightCheck(
                id="requires_cli_missing", level=hard_level,
                message=f"Required CLI '{cid}' not on PATH.",
                detail=_reason(item),
            ))

    # Environment variables (presence only — never reads values)
    for item in req.get("env") or []:
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name and not os.environ.get(name):
            checks.append(PreflightCheck(
                id="requires_env_missing", level=hard_level,
                message=f"Required environment variable '{name}' is unset.",
                detail=_reason(item),
            ))

    # MCP servers (best-effort)
    mcp_items = req.get("mcp") or []
    listing = _mcp_listing() if mcp_items else None
    for item in mcp_items:
        server = item.get("server") if isinstance(item, dict) else str(item)
        if not server:
            continue
        if listing is None:
            checks.append(PreflightCheck(
                id="requires_mcp_unknown", level=LEVEL_WARN,
                message=f"Could not verify MCP server '{server}' (claude mcp list unavailable).",
            ))
        elif server.lower() not in listing:
            checks.append(PreflightCheck(
                id="requires_mcp_missing", level=hard_level,
                message=f"Required MCP server '{server}' not registered.",
            ))

    if not checks:
        checks.append(PreflightCheck(
            id="requires_ok", level=LEVEL_INFO,
            message="All declared capability requirements satisfied.",
        ))
    return checks


def _check_git_state(project_dir: str) -> list[PreflightCheck]:
    """Warn if the working tree has uncommitted changes."""
    try:
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=False, cwd=project_dir,
        )
        if r.returncode != 0:
            return []  # Not a git repo or git not available
        dirty_lines = [line for line in r.stdout.splitlines() if line.strip()]
        if dirty_lines:
            return [PreflightCheck(
                id="dirty_worktree", level=LEVEL_WARN,
                message=f"Working tree has {len(dirty_lines)} uncommitted change(s).",
                detail="The agent may be confused by existing modifications. Consider committing first.",
            )]
    except Exception as e:
        logger.warning("preflight.py unexpected error: %s", e, exc_info=True)
        pass
    return [PreflightCheck(id="git_clean", level=LEVEL_INFO, message="Working tree is clean.")]


def _check_prior_failures(project_dir: str, task_id: str) -> list[PreflightCheck]:
    """Info/warn if this task has prior recorded failures."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import failures_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            rows = failures_dao.get_recent(conn, task_id=task_id)
        finally:
            conn.close()
        if not rows:
            return []
        level = LEVEL_WARN
        msg = f"{len(rows)} prior failure(s) recorded"
        msg += " — fix hints will be injected into context."
        return [PreflightCheck(id="prior_failures", level=level, message=msg)]
    except Exception as e:
        logger.warning("preflight.py unexpected error: %s", e, exc_info=True)
        return []


# ---------------------------------------------------------------------------
# Complexity estimate → fanout suggestion
# ---------------------------------------------------------------------------

def _estimate_complexity(task: dict) -> tuple[int, str]:
    """Return (suggested_fanout_n, suggested_mode) based on task scope."""
    ac = task.get("acceptance_criteria") or []
    tdd = task.get("tdd") or {}
    tdd_text = " ".join(str(v) for v in tdd.values())
    title = str(task.get("title", ""))

    # Score complexity
    score = 0
    score += len(ac)                                    # each criterion adds 1
    score += 2 if len(tdd_text) > 300 else 0           # complex TDD description
    score += 2 if any(w in title.lower() for w in     # high-complexity signals
                      ("refactor", "migrate", "rewrite", "architecture", "system")) else 0
    score += 1 if len(tdd_text) > 100 else 0

    if score <= 3:
        return 1, "single"
    elif score <= 6:
        return 2, "fanout"
    else:
        return 3, "swarm"


# ---------------------------------------------------------------------------
# Mandate policy — project-level rule that forces explicit requires: on
# tasks matching high-risk criteria (ship_on_complete, effort tier, test_types).
#
# Unlike signal-derive (which auto-fills the requires block), mandate enforces
# *operator intentionality*: the human must explicitly call
# `shux task requires --id <id> ...` for matched tasks. Signal-derived and
# project-baseline requirements do NOT satisfy the mandate — only a per-task
# requires: block does.
#
# Configure in .superharness/profile.yaml:
#   mandate_requires_for:
#     ship_on_complete: true          # tasks that auto-ship need explicit deps
#     effort: [high, max]             # high-effort tasks need explicit deps
#     test_types: [security, sast]    # security tasks need explicit deps
# ---------------------------------------------------------------------------

def _check_mandate_policy(task: dict, project_dir: str) -> list[PreflightCheck]:
    """Block dispatch if task matches a mandate profile but has no explicit requires: block.

    Reads ``mandate_requires_for:`` from .superharness/profile.yaml.  Returns
    an empty list when no policy is configured (fully opt-in, no impact on
    existing projects).
    """
    profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.exists(profile_path):
        return []
    try:
        import yaml as _yaml
        with open(profile_path) as _f:
            profile = _yaml.safe_load(_f) or {}
        mandate = profile.get("mandate_requires_for")
        if not isinstance(mandate, dict) or not mandate:
            return []
    except Exception as e:
        logger.warning("preflight.py mandate_requires_for load failed: %s", e)
        return []

    matched: list[str] = []

    # Criterion: ship_on_complete
    if mandate.get("ship_on_complete"):
        ship = task.get("ship_on_complete")
        if not ship:
            try:
                import json as _j
                raw = task.get("extras_json")
                if isinstance(raw, str):
                    ship = _j.loads(raw).get("ship_on_complete")
            except Exception:
                pass
        if ship:
            matched.append("ship_on_complete=true")

    # Criterion: effort tier
    effort_mandate = mandate.get("effort")
    if effort_mandate:
        if isinstance(effort_mandate, str):
            effort_mandate = [effort_mandate]
        task_effort = str(task.get("effort") or "").lower()
        if task_effort and task_effort in {str(e).lower() for e in effort_mandate}:
            matched.append(f"effort={task_effort}")

    # Criterion: test_types intersection
    tt_mandate = mandate.get("test_types")
    if tt_mandate:
        if isinstance(tt_mandate, str):
            tt_mandate = [tt_mandate]
        task_tt = {str(t).lower() for t in (task.get("test_types") or [])}
        hit = task_tt & {str(t).lower() for t in tt_mandate}
        if hit:
            matched.append(f"test_types=[{','.join(sorted(hit))}]")

    if not matched:
        return []

    criteria_str = ", ".join(matched)
    per_task_req = task.get("requires")
    if isinstance(per_task_req, dict) and per_task_req:
        return [PreflightCheck(
            id="mandate_requires_satisfied",
            level=LEVEL_INFO,
            message=f"Mandate satisfied: task matches {criteria_str} and has an explicit requires: block.",
        )]

    task_id = str(task.get("id", "?"))
    return [PreflightCheck(
        id="mandate_requires_missing",
        level=LEVEL_BLOCK,
        message=f"Mandate: task matches {criteria_str} but has no explicit requires: block.",
        detail=(
            f"Declare requirements via: shux task requires --id {task_id} --cli <tool> --env <VAR>"
            "\nOr opt out: remove 'mandate_requires_for' from .superharness/profile.yaml"
        ),
    )]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_preflight(
    project_dir: str,
    task: dict,
    skip_git: bool = False,
) -> PreflightReport:
    """Run all pre-flight checks for a task and return a PreflightReport.

    Args:
        project_dir: Absolute project root directory.
        task: Task dict from contract.yaml.
        skip_git: Skip git working-tree check (useful in tests / CI).
    """
    task_id = str(task.get("id", "unknown"))
    checks: list[PreflightCheck] = []

    checks.extend(_check_spec_complete(task))
    checks.extend(_check_tdd_block(task))
    checks.extend(_check_acceptance_criteria(task))

    checks.extend(_check_dependencies(task, project_dir))
    checks.extend(_check_requires(task, project_dir))
    checks.extend(_check_mandate_policy(task, project_dir))

    if not skip_git:
        checks.extend(_check_git_state(project_dir))

    checks.extend(_check_prior_failures(project_dir, task_id))

    # Determine overall status
    has_block = any(c.level == LEVEL_BLOCK for c in checks)
    has_warn = any(c.level == LEVEL_WARN for c in checks)
    if has_block:
        status = STATUS_BLOCK
    elif has_warn:
        status = STATUS_WARN
    else:
        status = STATUS_PASS

    fanout_n, mode = _estimate_complexity(task)

    return PreflightReport(
        task_id=task_id,
        status=status,
        checks=checks,
        suggested_fanout_n=fanout_n,
        suggested_mode=mode,
        can_dispatch=not has_block,
    )
