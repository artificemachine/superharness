"""shux onboard — interactive (or non-interactive) 7-step setup wizard.

Steps:
  1. detect   — detect project stack
  2. init     — scaffold .superharness/ (skipped if already exists)
  3. git_track — configure .gitignore for team/solo mode
  4. doctor   — run health checks (non-blocking)
  5. task     — create a first task in contract.yaml
  6. delegate — enqueue the task to inbox.yaml
  7. summary  — print next steps
"""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml


# ---------------------------------------------------------------------------
# Step status helpers
# ---------------------------------------------------------------------------

_STEPS = ["detect", "init", "git_track", "doctor", "task", "delegate", "summary"]

_INNER_GITIGNORE_ENTRIES = [
    "watcher-env.yaml",
    "launcher-logs/",
    "daemon.pid.json",
    "onboarding.yaml",
]


def _load_state(sh: Path) -> dict:
    state_file = sh / "onboarding.yaml"
    if state_file.exists():
        doc = yaml.safe_load(state_file.read_text()) or {}
        if isinstance(doc, dict) and "steps" in doc:
            return doc
    return {
        "version": 1,
        "steps": {s: "pending" for s in _STEPS},
    }


def _save_state(sh: Path, state: dict) -> None:
    (sh / "onboarding.yaml").write_text(yaml.dump(state, default_flow_style=False))


def _is_completed(state: dict, step: str) -> bool:
    return state.get("steps", {}).get(step) == "completed"


def _mark(state: dict, step: str) -> None:
    state.setdefault("steps", {})[step] = "completed"


# ---------------------------------------------------------------------------
# Detect helpers
# ---------------------------------------------------------------------------

def _detect_stack(project: Path) -> str:
    """Heuristic stack detection."""
    if (project / "pyproject.toml").exists() or (project / "setup.py").exists():
        return "Python"
    if (project / "package.json").exists():
        return "Node.js"
    if (project / "Cargo.toml").exists():
        return "Rust"
    if (project / "go.mod").exists():
        return "Go"
    if (project / "Gemfile").exists():
        return "Ruby"
    return "unknown"


def _is_git_repo(project: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(project), "rev-parse", "--git-dir"],
            capture_output=True,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Step implementations
# ---------------------------------------------------------------------------

def _step_detect(project: Path, state: dict) -> None:
    if _is_completed(state, "detect"):
        click.echo("[skip] Step 1 (detect): already completed")
        return
    stack = _detect_stack(project)
    is_git = _is_git_repo(project)
    git_label = "git repo" if is_git else "no git"
    click.echo(f"[detect] Project stack: {stack} ({git_label}) — found at {project}")
    _mark(state, "detect")


def _step_init(project: Path, state: dict) -> None:
    sh = project / ".superharness"
    if _is_completed(state, "init"):
        click.echo("[skip] Step 2 (init): already completed")
        return
    if sh.exists() and (sh / "contract.yaml").exists():
        click.echo("[skip] Step 2 (init): .superharness/ already exists")
        _mark(state, "init")
        return
    # Create scaffold
    sh.mkdir(exist_ok=True)
    contract = sh / "contract.yaml"
    if not contract.exists():
        contract.write_text("id: main\ntasks: []\n")
    ledger = sh / "ledger.md"
    if not ledger.exists():
        ledger.write_text("# Ledger\n")
    click.echo("[init] Initialized .superharness/")
    _mark(state, "init")


def _step_git_track(project: Path, state: dict, git_mode: str) -> None:
    sh = project / ".superharness"

    if _is_completed(state, "git_track"):
        click.echo("[skip] Step 3 (git_track): already completed")
        return

    if not _is_git_repo(project):
        click.echo("[skip] Step 3 (git_track): no git repo detected")
        _mark(state, "git_track")
        return

    # Root .gitignore
    gitignore = project / ".gitignore"
    if git_mode == "solo":
        existing = gitignore.read_text() if gitignore.exists() else ""
        if ".superharness" not in existing:
            with gitignore.open("a") as f:
                f.write("\n# superharness — local only\n.superharness/\n")
        click.echo("[git_track] Added .superharness/ to root .gitignore (solo mode)")
    else:
        # team mode: ensure .superharness is NOT in root .gitignore
        click.echo("[git_track] Team mode: .superharness/ will be committed")

    # Inner .gitignore always created
    inner = sh / ".gitignore"
    inner_lines = set(inner.read_text().splitlines()) if inner.exists() else set()
    added = False
    for entry in _INNER_GITIGNORE_ENTRIES:
        if entry not in inner_lines:
            inner_lines.add(entry)
            added = True
    if added or not inner.exists():
        inner.write_text("\n".join(sorted(inner_lines)) + "\n")
    click.echo("[git_track] Created/updated .superharness/.gitignore")

    _mark(state, "git_track")


def _step_doctor(project: Path, state: dict) -> None:
    if _is_completed(state, "doctor"):
        click.echo("[skip] Step 4 (doctor): already completed")
        return
    # Run doctor non-blocking — warnings are informational only
    try:
        r = subprocess.run(
            [sys.executable, "-m", "superharness.commands.doctor", "--project", str(project)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            click.echo(f"[doctor] Warning: some checks failed (non-blocking):\n{r.stdout.strip()}")
        else:
            click.echo("[doctor] All checks passed")
    except FileNotFoundError:
        click.echo("[doctor] Warning: could not run doctor (non-blocking)")
    _mark(state, "doctor")


def _step_task(project: Path, state: dict, task_title: Optional[str]) -> Optional[str]:
    """Create first task. Returns task_id or None."""
    if _is_completed(state, "task"):
        click.echo("[skip] Step 5 (task): already completed")
        return state.get("task_id")

    if not task_title:
        click.echo("[task] Skipped (no --task-title provided)")
        _mark(state, "task")
        return None

    sh = project / ".superharness"
    contract_file = sh / "contract.yaml"
    doc = yaml.safe_load(contract_file.read_text()) if contract_file.exists() else {"id": "main", "tasks": []}
    doc = doc or {"id": "main", "tasks": []}
    tasks = doc.get("tasks") or []

    task_id = f"t-{uuid.uuid4().hex[:6]}"
    now = datetime.now(timezone.utc).isoformat()
    task = {
        "id": task_id,
        "title": task_title,
        "status": "todo",
        "owner": "claude-code",
        "project_path": str(project),
        "created_at": now,
    }
    tasks.append(task)
    doc["tasks"] = tasks
    contract_file.write_text(yaml.dump(doc, default_flow_style=False))
    click.echo(f"[task] Created task '{task_title}' (id: {task_id})")
    _mark(state, "task")
    state["task_id"] = task_id
    return task_id


def _step_delegate(project: Path, state: dict, enqueue: bool, task_id: Optional[str]) -> None:
    if _is_completed(state, "delegate"):
        click.echo("[skip] Step 6 (delegate): already completed")
        return

    if not enqueue or not task_id:
        click.echo("[delegate] Skipped (no --enqueue or no task)")
        _mark(state, "delegate")
        return

    sh = project / ".superharness"
    inbox = sh / "inbox.yaml"
    items = yaml.safe_load(inbox.read_text()) if inbox.exists() else []
    items = items or []

    now = datetime.now(timezone.utc).isoformat()
    item = {
        "task_id": task_id,
        "target": "claude-code",
        "enqueued_at": now,
        "project_path": str(project),
    }
    items.append(item)
    inbox.write_text(yaml.dump(items, default_flow_style=False))
    click.echo(f"[delegate] Enqueued task {task_id} to inbox.yaml")
    _mark(state, "delegate")


def _step_summary(project: Path, state: dict) -> None:
    if _is_completed(state, "summary"):
        click.echo("[skip] Step 7 (summary): already completed")
        return

    click.echo("")
    click.echo("superharness is set up for this project.")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  shux contract     — view all tasks")
    click.echo("  shux delegate     — hand a task to an agent")
    click.echo("  shux doctor       — re-run health checks")
    click.echo("  shux dashboard    — open browser dashboard")
    _mark(state, "summary")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@click.command(name="onboard")
@click.option("--project", default=None, help="Project directory (default: cwd)")
@click.option("--non-interactive", "non_interactive", is_flag=True, default=False)
@click.option("--git-mode", "git_mode", type=click.Choice(["team", "solo"]), default="team")
@click.option("--task-title", "task_title", default=None)
@click.option("--enqueue", is_flag=True, default=False)
def cmd_onboard(
    project: Optional[str],
    non_interactive: bool,
    git_mode: str,
    task_title: Optional[str],
    enqueue: bool,
) -> None:
    """Interactive (or non-interactive) setup wizard for a new project."""
    project_path = Path(project).resolve() if project else Path.cwd()
    sh = project_path / ".superharness"

    # Ensure .superharness exists before loading state (init step will scaffold it properly)
    # We need the dir for state; create it minimally here so state file can be written.
    sh.mkdir(exist_ok=True)

    state = _load_state(sh)

    _step_detect(project_path, state)
    _save_state(sh, state)

    _step_init(project_path, state)
    _save_state(sh, state)

    _step_git_track(project_path, state, git_mode)
    _save_state(sh, state)

    _step_doctor(project_path, state)
    _save_state(sh, state)

    task_id = _step_task(project_path, state, task_title)
    _save_state(sh, state)

    _step_delegate(project_path, state, enqueue, task_id)
    _save_state(sh, state)

    _step_summary(project_path, state)
    _save_state(sh, state)
