"""shux onboard — interactive (or non-interactive) 7-step setup wizard.

Steps:
  1. detect        — detect project stack
  2. init          — scaffold .superharness/ + write project AGENTS.md
  2b. global_claude — append superharness section to ~/.claude/CLAUDE.md
  3. git_track     — configure .gitignore for team/solo mode
  4. doctor        — run health checks (non-blocking)
  5. task          — create a first task in contract.yaml
  6. delegate      — enqueue the task to inbox.yaml
  7. summary       — print next steps
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

_STEPS = ["detect", "init", "global_claude", "git_track", "doctor", "task", "delegate", "summary"]

_INNER_GITIGNORE_ENTRIES = [
    "watcher-env.yaml",
    "launcher-logs/",
    "daemon-state.json",
    "operator-state.json",
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
    click.echo(f"  → superharness will use this to tailor agent instructions and task defaults.")
    _mark(state, "detect")


_AGENTS_MD_TEMPLATE = """\
# superharness — agent instructions

## Before starting work
- Run `shux contract` to see all tasks and their status.
- Run `shux recall "<keywords>"` to search prior session context.
- Read `.superharness/contract.yaml`, `failures.yaml`, and handoffs addressed to you.

## Task lifecycle
Every task follows: `todo → plan_proposed → plan_approved → in_progress → report_ready → done`

- Set status to `plan_proposed` and write a plan handoff before implementing anything.
- Only implement after the operator sets status to `plan_approved`.
- After implementation, write a report handoff and set status to `report_ready`.
- Never self-close a task — only the operator runs `shux close <id>`.

## Key commands
- `shux contract`          — view all tasks
- `shux delegate <id>`     — enqueue a task for dispatch
- `shux verify <id>`       — record verification before closing
- `shux close <id>`        — mark a task done
- `shux hygiene`           — validate protocol compliance
- `shux recall "<words>"`  — search past handoffs and decisions
- `shux recap`             — what happened in the last N hours
- `shux inbox-gc`          — reconcile stale inbox items
- `shux worktree-gc`       — clean orphaned dispatch worktrees

## Protocol
- Keep `.superharness/` updated before stopping.
- Never commit `.env`, credentials, or secrets.
- Never push directly to `main`.
"""


def _step_init(project: Path, state: dict) -> None:
    sh = project / ".superharness"
    if _is_completed(state, "init"):
        click.echo("[skip] Step 2 (init): already completed")
        return
    already_existed = sh.exists() and (sh / "contract.yaml").exists()
    if already_existed:
        click.echo("[skip] Step 2 (init): .superharness/ already exists")
    else:
        # Create scaffold
        sh.mkdir(exist_ok=True)
        contract = sh / "contract.yaml"
        if not contract.exists():
            contract.write_text("id: main\ntasks: []\n")
        ledger = sh / "ledger.md"
        if not ledger.exists():
            ledger.write_text("# Ledger\n")
        decisions = sh / "decisions.yaml"
        if not decisions.exists():
            decisions.write_text("[]\n")
        failures = sh / "failures.yaml"
        if not failures.exists():
            failures.write_text("[]\n")
        handoffs = sh / "handoffs"
        handoffs.mkdir(exist_ok=True)
        click.echo("[init] Initialized .superharness/")
        click.echo("  → contract.yaml  tracks every task and its status.")
        click.echo("  → ledger.md      is the session history agents read first.")

    # Always write AGENTS.md if missing — this is what tells Claude/Codex to use shux
    agents_md = project / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(_AGENTS_MD_TEMPLATE)
        click.echo("[init] Wrote AGENTS.md")
        click.echo("  → AGENTS.md tells Claude Code and Codex CLI to use shux commands.")
        click.echo("  → Without it, agents won't know superharness is installed.")

    _mark(state, "init")


_GLOBAL_CLAUDE_MD_BLOCK = """
## superharness

`shux` is installed globally. In any superharness project:
- Run `shux contract` at the start of every session to see all tasks.
- Use `shux delegate <id>` to hand work to an agent.
- Use `shux close <id>` to mark a task done after verification.
- If no `.superharness/` exists yet in this project, run `shux onboard`.

Key commands: shux contract · shux delegate · shux dashboard · shux recap · shux close
"""


def _global_claude_md_path() -> Path:
    """Return path to global CLAUDE.md, overridable via env var for testing."""
    override = os.environ.get("SUPERHARNESS_GLOBAL_CLAUDE_MD")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "CLAUDE.md"


def _step_global_claude_md(state: dict) -> None:
    """Append a superharness section to ~/.claude/CLAUDE.md if not already present."""
    if _is_completed(state, "global_claude"):
        click.echo("[skip] Step 2b (global_claude): already completed")
        return

    path = _global_claude_md_path()

    if not path.exists():
        click.echo("[skip] Step 2b (global_claude): ~/.claude/CLAUDE.md not found — skipping")
        click.echo("  → If you use a global CLAUDE.md, add a superharness section manually.")
        _mark(state, "global_claude")
        return

    content = path.read_text(encoding="utf-8")
    if "superharness" in content.lower():
        click.echo("[skip] Step 2b (global_claude): superharness already in global CLAUDE.md")
        _mark(state, "global_claude")
        return

    with path.open("a", encoding="utf-8") as f:
        f.write(_GLOBAL_CLAUDE_MD_BLOCK)

    click.echo(f"[global_claude] Appended superharness section to {path}")
    click.echo("  → Every Claude Code session on this machine now knows to use shux.")
    click.echo("  → Works across ALL projects, not just this one.")
    _mark(state, "global_claude")


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
        click.echo("  → solo mode: task state is local only, not shared with teammates.")
        click.echo("  → Use --git-mode team to commit task state for shared projects.")
    else:
        # team mode: ensure .superharness is NOT in root .gitignore
        click.echo("[git_track] Team mode: .superharness/ will be committed")
        click.echo("  → team mode: task state is committed — your whole team shares it.")

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
    click.echo("  → Runtime files (logs, daemon pid, watcher env) excluded from commits.")

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
            click.echo("  → These won't stop you — proceed and run 'shux doctor' to fix later.")
        else:
            click.echo("[doctor] All checks passed")
            click.echo("  → Your environment is ready for agent dispatch.")
    except FileNotFoundError:
        click.echo("[doctor] Warning: could not run doctor (non-blocking)")
        click.echo("  → Run 'shux doctor' manually once your PATH is configured.")
    _mark(state, "doctor")


def _step_task(project: Path, state: dict, task_title: Optional[str]) -> Optional[str]:
    """Create first task. Returns task_id or None."""
    if _is_completed(state, "task"):
        click.echo("[skip] Step 5 (task): already completed")
        return state.get("task_id")

    if not task_title:
        click.echo("[task] Skipped (no --task-title provided)")
        click.echo("  → Add your first task later: shux task create --title \"...\"")
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
    click.echo(f"  → Task lives in contract.yaml. Run 'shux contract' to see it.")
    click.echo(f"  → Next: approve the plan, then 'shux delegate {task_id}' to dispatch.")
    _mark(state, "task")
    state["task_id"] = task_id
    return task_id


def _step_delegate(project: Path, state: dict, enqueue: bool, task_id: Optional[str]) -> None:
    if _is_completed(state, "delegate"):
        click.echo("[skip] Step 6 (delegate): already completed")
        return

    if not enqueue or not task_id:
        click.echo("[delegate] Skipped (no --enqueue or no task)")
        click.echo("  → When ready: shux delegate <task-id> to hand work to an agent.")
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
    click.echo("  → The watcher picks this up within 30s and launches the agent.")
    click.echo("  → Run 'shux daemon start' to keep the watcher running in the background.")
    _mark(state, "delegate")


def _step_summary(project: Path, state: dict) -> None:
    if _is_completed(state, "summary"):
        click.echo("[skip] Step 7 (summary): already completed")
        return

    click.echo("")
    click.echo("superharness is set up for this project.")
    click.echo("")
    click.echo("  → AGENTS.md written — Claude Code and Codex now know to use shux.")
    click.echo("  → Open Claude Code or Codex in this project and they'll follow the protocol.")
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

    click.echo("")
    click.echo("superharness — what is it?")
    click.echo("==========================")
    click.echo("")
    click.echo("  You delegate work to AI agents (Claude Code, Codex CLI, etc.).")
    click.echo("  They forget context between sessions. Work gets lost or duplicated.")
    click.echo("")
    click.echo("  superharness fixes that with three files:")
    click.echo("    contract.yaml  — single source of truth for every task")
    click.echo("    handoffs/      — context passed between agents (nothing lost)")
    click.echo("    inbox.yaml     — tasks queued, dispatched, and tracked")
    click.echo("")
    click.echo("  The flow:")
    click.echo("    task → delegate → agent works → handoff → verify → close")
    click.echo("")
    click.echo("  Core commands:")
    click.echo("    shux contract          view all tasks and their status")
    click.echo("    shux delegate <id>     hand a task to an agent")
    click.echo("    shux dashboard         open the browser dashboard")
    click.echo("    shux close <id>        mark a task done")
    click.echo("    shux doctor            check environment health")
    click.echo("")
    click.echo("  Maintenance:")
    click.echo("    shux recap             what happened recently")
    click.echo("    shux inbox-gc          clean stale inbox items")
    click.echo("    shux worktree-gc       clean orphaned worktrees")
    click.echo("    shux status            watcher + inbox health")
    click.echo("")
    click.echo("Setting up this project now...")
    click.echo("")

    # Ensure .superharness exists before loading state (init step will scaffold it properly)
    # We need the dir for state; create it minimally here so state file can be written.
    sh.mkdir(exist_ok=True)

    state = _load_state(sh)

    _step_detect(project_path, state)
    _save_state(sh, state)

    _step_init(project_path, state)
    _save_state(sh, state)

    _step_global_claude_md(state)
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
