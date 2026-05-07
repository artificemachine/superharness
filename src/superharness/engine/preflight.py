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
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


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


def _check_dependencies(task: dict, contract_file: str) -> list[PreflightCheck]:
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
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(contract_file)))
        tasks = _sr.get_tasks(project_dir)
        tasks_by_id = {str(t.get("id", "")): t for t in tasks if isinstance(t, dict)}
    except Exception:
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
    except Exception:
        pass
    return [PreflightCheck(id="git_clean", level=LEVEL_INFO, message="Working tree is clean.")]


def _check_prior_failures(project_dir: str, task_id: str) -> list[PreflightCheck]:
    """Info/warn if this task has prior recorded failures."""
    try:
        failures_file = Path(project_dir) / ".superharness" / "failures.yaml"
        if not failures_file.exists():
            return []
        import yaml
        data = yaml.safe_load(failures_file.read_text(encoding="utf-8")) or {}
        task_failures = [e for e in (data.get("failures") or []) if e.get("task") == task_id]
        if not task_failures:
            return []
        critical = [e for e in task_failures if e.get("severity") == "critical"]
        level = LEVEL_BLOCK if critical else LEVEL_WARN
        msg = f"{len(task_failures)} prior failure(s) recorded"
        if critical:
            msg += f" ({len(critical)} critical)"
        msg += " — fix hints will be injected into context."
        return [PreflightCheck(id="prior_failures", level=level, message=msg)]
    except Exception:
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
# Main entry point
# ---------------------------------------------------------------------------

def run_preflight(
    project_dir: str,
    task: dict,
    contract_file: str = "",
    skip_git: bool = False,
) -> PreflightReport:
    """Run all pre-flight checks for a task and return a PreflightReport.

    Args:
        project_dir: Absolute project root directory.
        task: Task dict from contract.yaml.
        contract_file: Path to contract.yaml (for dependency checks).
        skip_git: Skip git working-tree check (useful in tests / CI).
    """
    task_id = str(task.get("id", "unknown"))
    checks: list[PreflightCheck] = []

    checks.extend(_check_spec_complete(task))
    checks.extend(_check_tdd_block(task))
    checks.extend(_check_acceptance_criteria(task))

    if contract_file and os.path.isfile(contract_file):
        checks.extend(_check_dependencies(task, contract_file))

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
