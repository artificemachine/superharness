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
    for t in (contract.get("tasks") or []):
        if isinstance(t, dict) and str(t.get("id", "")) == task_id:
            return t
    return None


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
            ["git", "-C", str(project_dir), "log", "--format=", "--name-only", "-10"],
            capture_output=True, text=True,
        )
        files: set[str] = set()
        for line in r2.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                files.add(stripped)
        return sorted(files)[:10]
    except (OSError, subprocess.SubprocessError, FileNotFoundError):
        return None


def task_context(project_dir: Path | str, task_id: str | None) -> str:
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

    sep = "═" * 44
    lines = [
        sep,
        f" Context: {task_id}  (owner: {task.get('owner', 'unknown')})",
        sep,
        f"Status: {task.get('status', 'unknown')}",
        f"Title:  {task.get('title', '')}",
    ]

    # Last handoff
    handoffs_dir = sh_dir / "handoffs"
    handoff = _find_latest_handoff(handoffs_dir, task_id)
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

    # Decisions
    decisions_path = sh_dir / "decisions.yaml"
    if decisions_path.exists():
        doc = _load_yaml_safe(decisions_path)
        decisions = (doc.get("decisions") or []) if isinstance(doc, dict) else []
        relevant = _filter_entries(decisions, task_id)
        if relevant:
            lines.append("")
            lines.append("Decisions relevant to this task:")
            for d in relevant[:5]:
                if isinstance(d, dict):
                    date_s = str(d.get("date", ""))[:10]
                    text = d.get("decision") or d.get("description") or str(d)
                    lines.append(f"  - [{date_s}] {text}")

    # Failures
    failures_path = sh_dir / "failures.yaml"
    if failures_path.exists():
        doc = _load_yaml_safe(failures_path)
        failures = (doc.get("failures") or []) if isinstance(doc, dict) else []
        relevant = _filter_entries(failures, task_id)
        if relevant:
            lines.append("")
            lines.append("Failures relevant to this task:")
            for f in relevant[:5]:
                if isinstance(f, dict):
                    date_s = str(f.get("date", ""))[:10]
                    text = f.get("failure") or f.get("description") or str(f)
                    lines.append(f"  - [{date_s}] {text}")

    # Ledger
    ledger_path = sh_dir / "ledger.md"
    ledger_lines = _ledger_lines_for_task(ledger_path, task_id)
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

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="context",
        description="Show full context for a task: last handoff, decisions, failures, ledger, git.",
    )
    parser.add_argument("--project", "-p", default=None, help="Project directory (default: cwd)")
    parser.add_argument(
        "task_id", nargs="?", default=None,
        help="Task ID (default: auto-select first active task)",
    )
    opts = parser.parse_args(argv)

    project_dir = os.path.realpath(opts.project or os.getcwd())
    output = task_context(project_dir, opts.task_id)

    if output.startswith("Error:"):
        print(output, file=sys.stderr)
        sys.exit(1)

    print(output)


if __name__ == "__main__":
    main()
