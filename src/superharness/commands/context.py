"""superharness context — show full context for a task.

Surfaces: task status, last handoff (outcome + context fields), relevant
decisions, relevant failures, recent ledger entries, and recently changed files
from git log.

Usage:
    superharness context [--project DIR] [task-id]

If task-id is omitted, the first in_progress / plan_proposed / plan_approved /
report_ready task in the contract is selected automatically.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _load_yaml_safe(path: Path) -> object:
    try:
        import yaml
        return yaml.safe_load(path.read_text(errors="replace")) or {}
    except Exception:
        return {}


def _find_task(contract: dict, task_id: str) -> dict | None:
    """Return a task dict by id. Also resolves subtask ids (e.g. "parent.1").

    For a subtask, returns a shallow copy with two extra keys:
      - "_parent_id": the owning top-level task id
      - "_effective_status": status resolved via inheritance from parent
    """
    from superharness.engine.subtask import (
        find_task_or_subtask,
        resolve_subtask_status,
    )
    task, parent = find_task_or_subtask(contract, task_id)
    if task is None:
        return None
    if parent is None:
        return task
    enriched = dict(task)
    enriched["_parent_id"] = str(parent.get("id", ""))
    enriched["_effective_status"] = resolve_subtask_status(
        task, str(parent.get("status", ""))
    )
    return enriched


def _find_active_task_id(contract: dict) -> str | None:
    active_statuses = {"in_progress", "plan_proposed", "plan_approved", "report_ready"}
    for t in (contract.get("tasks") or []):
        if isinstance(t, dict) and t.get("status") in active_statuses:
            return str(t.get("id", ""))
    return None


def _find_latest_handoff(handoffs_dir: Path, task_id: str) -> dict | None:
    """Return parsed YAML of the most recent handoff file for this task."""
    if not handoffs_dir.is_dir():
        return None
    candidates = [f for f in handoffs_dir.glob("*.yaml") if task_id in f.name]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    data = _load_yaml_safe(latest)
    return data if isinstance(data, dict) else None


def _filter_entries(items: list, task_id: str) -> list[dict]:
    """Return entries mentioning task_id, or all entries if none match."""
    if not items:
        return []
    filtered = [e for e in items if isinstance(e, dict) and task_id in str(e)]
    return filtered if filtered else [e for e in items if isinstance(e, dict)]


def _ledger_lines_for_task(ledger_path: Path, task_id: str, n: int = 5) -> list[str]:
    if not ledger_path.exists():
        return []
    lines = ledger_path.read_text(errors="replace").splitlines()
    matching = [
        ln for ln in lines
        if task_id in ln and ln.strip() and not ln.strip().startswith("#")
    ]
    return matching[-n:]


def _git_changed_files(project_dir: Path) -> list[str] | None:
    """Return recently changed file paths, or None if not a git repo."""
    try:
        r = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--git-dir"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return None
        r2 = subprocess.run(
            ["git", "-C", str(project_dir), "log", "--format=", "--name-only", "-20"],
            capture_output=True, text=True,
        )
        files: set[str] = set()
        for line in r2.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                files.add(stripped)
        return sorted(files)[:20]
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        return None


def _filter_failures(failures: list, task_ids: list[str], failures_only: bool = False) -> list[dict]:
    """Return failures strictly for the set of task_ids.

    If failures_only is True, filter out 'minor' severity entries (warnings).
    """
    relevant = []
    id_set = set(task_ids)
    for f in failures:
        if not isinstance(f, dict):
            continue
        # Check if the failure belongs to any of the requested IDs
        if f.get("task") in id_set:
            if failures_only and f.get("severity") == "minor":
                continue
            relevant.append(f)
    return relevant


def task_context(
    project_dir: Path | str,
    task_id: str | None,
    failures_only: bool = False,
) -> str:
    """Build and return a formatted context block for the given task."""
    project_dir = Path(project_dir).resolve()
    sh_dir = project_dir / ".superharness"

    if not sh_dir.is_dir():
        return f"No .superharness/ found at {project_dir}"

    contract_path = sh_dir / "contract.yaml"
    contract = _load_yaml_safe(contract_path) if contract_path.exists() else {}
    if not isinstance(contract, dict):
        contract = {}

    # Auto-select task if not specified
    if not task_id:
        task_id = _find_active_task_id(contract)
        if not task_id:
            tasks = [t for t in (contract.get("tasks") or []) if isinstance(t, dict)]
            if not tasks:
                return "No tasks found in contract."
            lines = ["No active task found. All tasks:"]
            for t in tasks:
                lines.append(f"  {t.get('id', '?')}  {t.get('status', '?')}  {t.get('title', '')}")
            return "\n".join(lines)

    task = _find_task(contract, task_id)
    if task is None:
        return f"Error: task '{task_id}' not found in contract."

    parent_id = task.get("_parent_id")
    is_subtask = bool(parent_id)
    effective_status = task.get("_effective_status") or task.get("status", "unknown")

    sep = "═" * 44
    header_kind = "Subtask" if is_subtask else "Context"
    lines = [
        sep,
        f" {header_kind}: {task_id}  (owner: {task.get('owner', 'unknown')})",
        sep,
    ]
    if is_subtask:
        lines.append(f"Parent: {parent_id}")
        lines.append(f"Status: {effective_status}  (inherited from parent)")
    else:
        lines.append(f"Status: {task.get('status', 'unknown')}")
    lines.append(f"Title:  {task.get('title', '')}")

    # Handoffs/decisions/failures/ledger lookups use the parent id for subtasks
    # (subtasks don't have their own handoffs; they inherit the parent's).
    lookup_id = parent_id if is_subtask else task_id

    # Last handoff
    handoffs_dir = sh_dir / "handoffs"
    handoff = _find_latest_handoff(handoffs_dir, lookup_id)
    if handoff:
        date_raw = str(handoff.get("date", ""))[:10].strip()
        date_str = f" ({date_raw})" if date_raw else ""
        lines.append("")
        lines.append(f"Last handoff{date_str}:")
        if handoff.get("outcome"):
            outcome = str(handoff["outcome"]).strip().replace("\n", "\n           ")
            lines.append(f"  outcome: {outcome}")
        if handoff.get("context"):
            ctx_text = str(handoff["context"]).strip().replace("\n", "\n           ")
            lines.append(f"  context: {ctx_text}")
        if handoff.get("plan") and not handoff.get("outcome"):
            plan = str(handoff["plan"]).strip()[:200].replace("\n", "\n         ")
            lines.append(f"  plan: {plan}")
    else:
        lines.append("")
        lines.append("Last handoff: (none found)")

    # Decisions (from SQLite)
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import decisions_dao
        conn = get_connection(str(project_dir))
        try:
            init_db(conn)
            rows = decisions_dao.get_recent(conn, limit=100)
            decisions = []
            for row in rows:
                if row.task_id == lookup_id:
                    decisions.append({"date": row.created_at[:10] if row.created_at else "",
                                     "decision": row.decision or "", "reason": row.reason or ""})
        finally:
            conn.close()
    except Exception:
        decisions = []
    if decisions:
        lines.append("")
        lines.append("Decisions relevant to this task:")
        for d in decisions[:5]:
            date_s = str(d.get("date", ""))[:10]
            text = d.get("decision") or str(d)
            lines.append(f"  - [{date_s}] {text}")

    # Failures (from SQLite)
    try:
        from superharness.engine import failures_dao
        conn2 = get_connection(str(project_dir))
        try:
            init_db(conn2)
            rows = failures_dao.get_recent(conn2, task_id=lookup_id, limit=10)
            failures = []
            for row in rows:
                failures.append({"pattern": row.pattern or "unknown",
                                "error_snippet": row.error_snippet or "",
                                "created_at": row.created_at or ""})
        finally:
            conn2.close()
    except Exception:
        failures = []

    # Build set of relevant task IDs (self + blockers)
    relevant_ids = [lookup_id]
    blocked_by = task.get("blocked_by") or task.get("depends_on")
    if blocked_by and str(blocked_by).lower() != "none":
        if isinstance(blocked_by, str):
            relevant_ids.extend([d.strip() for d in blocked_by.split(",") if d.strip()])
        elif isinstance(blocked_by, list):
            relevant_ids.extend([str(d).strip() for d in blocked_by if d])

    relevant = _filter_failures(failures, relevant_ids, failures_only)
    if relevant:
        lines.append("")
        lines.append("Failures relevant to this task:")
        for f in relevant[:5]:
            if isinstance(f, dict):
                date_s = str(f.get("date", ""))[:10]
                sev = f.get("severity", "minor")
                patterns = ", ".join(f.get("patterns", []))
                task_label = f" [{f.get('task')}]" if f.get("task") != lookup_id else ""
                text = f.get("failure") or f.get("description") or f.get("error_snippet") or str(f)
                lines.append(f"  - [{date_s}] ({sev}){task_label} {patterns}: {text}")

    # Ledger
    ledger_path = sh_dir / "ledger.md"
    ledger_lines = _ledger_lines_for_task(ledger_path, lookup_id)
    if ledger_lines:
        lines.append("")
        lines.append("Recent ledger entries:")
        for ln in ledger_lines:
            lines.append(f"  {ln}")

    # Git changed files (omit section entirely if not a git repo)
    git_files = _git_changed_files(project_dir)
    if git_files is not None:
        lines.append("")
        if git_files:
            lines.append("Changed files (git log):")
            for f in git_files:
                lines.append(f"  {f}")
        else:
            lines.append("Changed files (git log): (none in last 10 commits)")

    lines.append(sep)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    import argparse

    # Windows consoles default to cp1252, which cannot encode the box-drawing
    # characters used in our output. Reconfigure stdout to UTF-8 when possible.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError, OSError):
        pass

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="context",
        description="Show full context for a task: last handoff, decisions, failures, ledger, git.",
    )
    parser.add_argument("--project", "-p", default=None, help="Project directory (default: cwd)")
    parser.add_argument(
        "--failures-only", action="store_true",
        help="Only show major/critical failures (hide warnings/minor entries)",
    )
    parser.add_argument(
        "task_id", nargs="?", default=None,
        help="Task ID (default: auto-select first active task)",
    )
    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    output = task_context(project_dir, opts.task_id, failures_only=opts.failures_only)

    if output.startswith("Error:"):
        print(output, file=sys.stderr)
        sys.exit(1)

    print(output)


if __name__ == "__main__":
    main()
