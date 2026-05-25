"""shux onboard — interactive (or non-interactive) 7-step setup wizard.

Steps:
  1. detect        — detect project stack
  2. init          — scaffold .superharness/ + write project AGENTS.md
  2b. global_claude — append superharness section to ~/.claude/CLAUDE.md
  3. git_track     — configure .gitignore for team/solo mode
  4. doctor        — run health checks (non-blocking)
   5. task          — create a first task in project state
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

from superharness.engine.db import get_connection, init_db
from superharness.engine import tasks_dao, inbox_dao
from superharness.engine.tasks_dao import TaskRow

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Step status helpers
# ---------------------------------------------------------------------------

_STEPS = ["detect", "init", "global_claude", "git_track", "doctor", "task", "delegate", "summary"]

# ---------------------------------------------------------------------------
# Config version — increment when new wizard steps are introduced.
# _STEPS_BY_VERSION maps version number → steps first introduced in that version.
# On load, steps from newer versions are reset to "pending" so they re-run.
# ---------------------------------------------------------------------------

ONBOARD_CONFIG_VERSION = 2
_STEPS_BY_VERSION: dict[int, list[str]] = {
    2: ["global_claude"],
}

_INNER_GITIGNORE_ENTRIES = [
    "watcher-env.yaml",
    "launcher-logs/",
    "daemon-state.json",
    "operator-state.json",
    "onboarding.yaml",
    "state.sqlite3",
    "state.sqlite3-shm",
    "state.sqlite3-wal",
    "events.jsonl",
]


def _apply_version_migrations(state: dict) -> None:
    """Reset steps introduced in newer config versions to 'pending'.

    Reads ``state["config_version"]`` (defaults to 1 when absent) and, for
    each version between stored+1 and ONBOARD_CONFIG_VERSION (inclusive),
    resets every step listed in ``_STEPS_BY_VERSION`` back to "pending".
    Updates ``state["config_version"]`` to the current value so the migration
    only runs once.
    """
    stored = int(state.get("config_version", 1))
    if stored >= ONBOARD_CONFIG_VERSION:
        return
    steps = state.setdefault("steps", {})
    for v in range(stored + 1, ONBOARD_CONFIG_VERSION + 1):
        for step_name in _STEPS_BY_VERSION.get(v, []):
            steps[step_name] = "pending"
    state["config_version"] = ONBOARD_CONFIG_VERSION


def _project_dir_from_sh(sh: Path) -> str:
    return str(sh.parent)


def _load_state(sh: Path) -> dict:
    """Load onboarding state: prefer fresher of SQLite vs YAML crash dump.

    C-DURABLE-READ (v11): if a SQLite write failed and the crash-dump YAML has
    fresher data, return YAML. Otherwise SQLite wins.
    """
    sqlite_doc: dict | None = None
    sqlite_ts = ""
    try:
        from superharness.engine import onboarding_dao
        project_dir = _project_dir_from_sh(sh)
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = onboarding_dao.get(conn)
        finally:
            conn.close()
        if row is not None:
            sqlite_doc = {
                "version": row.version,
                "config_version": row.config_version,
                "steps": dict(row.steps),
            }
            sqlite_ts = row.updated_at or ""
    except Exception as e:
        logger.debug("onboard: SQLite read failed: %s", e)

    yaml_doc: dict | None = None
    yaml_ts = ""
    state_file = sh / "onboarding.yaml"
    if state_file.exists():
        try:
            raw = yaml.safe_load(state_file.read_text()) or {}  # noqa: state-read — YAML compare-or-fallback (legacy + crash dumps)
            if isinstance(raw, dict) and "steps" in raw:
                yaml_doc = raw
                # YAML mirror doesn't store updated_at; we treat its mtime as the timestamp
                # so a fresh crash-dump (just written) wins over stale SQLite.
                try:
                    import datetime as _dt
                    yaml_ts = _dt.datetime.utcfromtimestamp(
                        state_file.stat().st_mtime
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except Exception:
                    yaml_ts = ""
        except Exception as e:
            logger.warning("onboard: YAML read error: %s", e)

    chosen: dict | None
    if sqlite_doc is None and yaml_doc is None:
        chosen = None
    elif sqlite_doc is None:
        chosen = yaml_doc
    elif yaml_doc is None:
        chosen = sqlite_doc
    else:
        chosen = yaml_doc if yaml_ts > sqlite_ts else sqlite_doc

    if chosen is not None:
        _apply_version_migrations(chosen)
        return chosen
    return {
        "version": 1,
        "config_version": ONBOARD_CONFIG_VERSION,
        "steps": {s: "pending" for s in _STEPS},
    }


def _save_state(sh: Path, state: dict) -> None:
    when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # SQLite primary — source of truth
    sqlite_ok = False
    try:
        from superharness.engine import onboarding_dao
        project_dir = _project_dir_from_sh(sh)
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            onboarding_dao.upsert(
                conn,
                version=int(state.get("version", 1)),
                config_version=int(state.get("config_version", ONBOARD_CONFIG_VERSION)),
                steps=dict(state.get("steps", {})),
                updated_at=when,
            )
            conn.commit()
            sqlite_ok = True
        finally:
            conn.close()
    except Exception as e:
        logger.error("onboard: SQLite SoT write failed — falling back to YAML crash dump: %s", e)

    # YAML mirror: skip only when SQLite succeeded AND sqlite_only mode is active.
    # If SQLite failed, write YAML regardless (C-DURABLE fallback).
    try:
        from superharness.engine.sqlite_only import is_sqlite_only
        if sqlite_ok and is_sqlite_only(project_dir=_project_dir_from_sh(sh)):
            return
    except Exception as e:
        logger.debug("onboard: is_sqlite_only check failed, writing YAML mirror: %s", e)

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
- Read the project state (`shux contract`) and handoffs addressed to you.

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
    from superharness.utils.paths import is_project_initialized
    already_existed = is_project_initialized(str(project))
    if already_existed:
        click.echo("[skip] Step 2 (init): .superharness/ already exists")
    else:
        # Create scaffold
        sh.mkdir(exist_ok=True)
        contract = sh / "contract.yaml"
        if not contract.exists():
            contract.write_text("id: main\ntasks: []\n", encoding="utf-8")
        ledger = sh / "ledger.md"
        if not ledger.exists():
            ledger.write_text("# Ledger\n", encoding="utf-8")
        decisions = sh / "decisions.yaml"
        if not decisions.exists():
            decisions.write_text("[]\n")
        failures = sh / "failures.yaml"
        if not failures.exists():
            failures.write_text("[]\n")
        handoffs = sh / "handoffs"
        handoffs.mkdir(exist_ok=True)
        
        # Initialize SQLite DB
        try:
            conn = get_connection(str(project))
            init_db(conn, str(project))
            conn.close()
            click.echo("[init] Initialized SQLite state database")
        except Exception as e:
            click.echo(f"[init] Warning: could not initialize SQLite database: {e}")

        click.echo("[init] Initialized .superharness/")
        click.echo("  → state.sqlite3  tracks every task and its status (use 'shux contract').")
        click.echo("  → ledger.md      is the session history agents read first.")

    # Always write AGENTS.md if missing — this is what tells Claude/Codex to use shux
    agents_md = project / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(_AGENTS_MD_TEMPLATE, encoding="utf-8")
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
    try:
        from superharness.engine import state_reader as _sr
        doc = _sr.get_contract_doc(str(project))
    except Exception as e:
        logger.warning("onboard.py unexpected error: %s", e, exc_info=True)
        doc = {"id": "main", "tasks": []}
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
    # Write contract through canonical path (syncs YAML + SQLite)
    try:
        from superharness.engine.contract_io import write_contract as _wc
        _wc(str(sh / "contract.yaml"), doc)
    except Exception as e:
        click.echo(f"[task] Warning: could not write contract: {e}")

    click.echo(f"[task] Created task '{task_title}' (id: {task_id})")
    click.echo(f"  → Task lives in project state. Run 'shux contract' to see it.")
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

    now = datetime.now(timezone.utc).isoformat()

    # Write to SQLite via inbox_dao (canonical path — SQLite is the sole source of truth)
    try:
        conn = get_connection(str(project))
        inbox_dao.enqueue(
            conn,
            id=f"auto-{uuid.uuid4().hex[:6]}",
            task_id=task_id,
            target_agent="claude-code",
            project_path=str(project),
            now=now,
        )
        conn.commit()
        conn.close()
    except Exception as e:
        click.echo(f"[delegate] Warning: could not enqueue inbox item to SQLite: {e}")

    click.echo(f"[delegate] Enqueued task {task_id} to inbox")
    click.echo("  → The watcher picks this up within 30s and launches the agent.")
    click.echo("  → Run 'shux daemon start' to keep the watcher running in the background.")
    _mark(state, "delegate")


_STEP_SYMBOLS: dict[str, str] = {
    "completed": "✓",
    "skipped":   "–",
    "pending":   "○",
}


def _step_summary(project: Path, state: dict) -> None:
    """Print per-step status table then the standard next-steps block."""
    click.echo("")
    click.echo("superharness is set up for this project.")
    click.echo("")
    click.echo("Setup status:")
    for step in _STEPS:
        if step == "summary":
            continue
        step_status = state.get("steps", {}).get(step, "pending")
        symbol = _STEP_SYMBOLS.get(step_status, "○")
        click.echo(f"  {symbol} {step}")
    click.echo("")
    click.echo("Next steps:")
    click.echo("  shux contract     — view all tasks")
    click.echo("  shux delegate     — hand a task to an agent")
    click.echo("  shux doctor       — re-run health checks")
    click.echo("  shux dashboard    — open browser dashboard")
    _mark(state, "summary")


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

DEFAULT_PROFILE: dict = {
    "_config_version": 1,
    "autonomy": "supervised",
    "plan_approval_gates": True,
    "default_agent": "claude-code",
    "round_tasks_skip_plan_approval": True,
    "git_mode": "team",
    "gateway": {
        "events": [],
    },
}


def _read_profile(project: Path) -> dict:
    profile_file = project / ".superharness" / "profile.yaml"
    if not profile_file.exists():
        return dict(DEFAULT_PROFILE)
    try:
        doc = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
        return doc if isinstance(doc, dict) else dict(DEFAULT_PROFILE)
    except Exception as e:
        logger.warning("onboard.py unexpected error: %s", e, exc_info=True)
        return dict(DEFAULT_PROFILE)


def _write_profile(project: Path, config: dict) -> None:
    (project / ".superharness").mkdir(exist_ok=True)
    (project / ".superharness" / "profile.yaml").write_text(
        yaml.dump(config, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def _ensure_config_version(project: Path) -> dict:
    """Load profile, backfill any missing DEFAULT_PROFILE keys, write back."""
    config = _read_profile(project)
    changed = False
    for k, v in DEFAULT_PROFILE.items():
        if k not in config:
            config[k] = v
            changed = True
    if changed:
        _write_profile(project, config)
    return config


# ---------------------------------------------------------------------------
# Section implementations (I3) — delegate to ui/sections/*
# ---------------------------------------------------------------------------

def _section_project(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.sections.project import run as _run
    _run(project, non_interactive=non_interactive)
    # Sync in-memory config from profile.yaml so later steps see updated values
    from superharness.engine.profile import read_field
    config["project_name"] = read_field(project, "project_name") or project.name
    config["stack"] = read_field(project, "stack") or _detect_stack(project)
    config.setdefault("status", "active")


def _section_agent(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.sections.agent import run as _run
    _run(project, non_interactive=non_interactive)
    from superharness.engine.profile import read_field
    config["autonomy"] = read_field(project, "autonomy")
    config["default_agent"] = read_field(project, "primary_agent")


def _section_git(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.sections.git import run as _run
    _run(project, non_interactive=non_interactive)
    from superharness.engine.profile import read_field
    config["git_mode"] = read_field(project, "git_mode") or config.get("git_mode", "team")


def _section_hooks(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.sections.hooks import run as _run
    _run(project, non_interactive=non_interactive)


def _section_watcher(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.sections.watcher import run as _run
    _run(project, non_interactive=non_interactive)
    from superharness.engine.profile import read_field
    config["watcher_backend"] = read_field(project, "watcher_backend")


def _section_gateway(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.sections.gateway import run as _run
    _run(project, non_interactive=non_interactive)


def _section_task(project: Path, config: dict, non_interactive: bool) -> None:
    from superharness.ui.prompts import print_header, print_info
    print_header("First task")
    print_info("Add your first task: shux task create --title \"...\"")


# ---------------------------------------------------------------------------
# Section registry
# ---------------------------------------------------------------------------

ONBOARD_SECTIONS: list[tuple[str, str, object]] = [
    ("project",  "Project identity",        _section_project),
    ("agent",    "Agent settings",          _section_agent),
    ("git",      "Git & tracking",          _section_git),
    ("hooks",    "Hooks",                   _section_hooks),
    ("watcher",  "Watcher daemon",          _section_watcher),
    ("gateway",  "Notifications",           _section_gateway),
    ("task",     "First task",              _section_task),
]

_SECTION_KEYS = [k for k, _, _ in ONBOARD_SECTIONS]


def _is_returning_user(project: Path) -> bool:
    from superharness.utils.paths import is_project_initialized
    return is_project_initialized(str(project))


def _print_noninteractive_guidance(project: Path) -> None:
    click.echo("")
    click.echo("superharness -- non-interactive mode")
    click.echo("  Configure using flags:")
    click.echo("    shux onboard --non-interactive --git-mode team --autonomy supervised")
    click.echo("  Or edit .superharness/profile.yaml directly.")
    click.echo("  Run 'shux onboard' in an interactive terminal for the full wizard.")
    click.echo("")
    click.echo("  Available sections:")
    for key, label, _ in ONBOARD_SECTIONS:
        click.echo(f"    shux onboard --section {key:<10}  {label}")
    click.echo("")


def _run_onboard_wizard(
    project_path: Path,
    non_interactive: bool,
    git_mode: str,
    task_title: Optional[str],
    enqueue: bool,
    section: Optional[str],
    quick: bool = False,
) -> None:
    sh = project_path / ".superharness"
    sh.mkdir(exist_ok=True)

    config = _ensure_config_version(project_path)
    if git_mode:
        config["git_mode"] = git_mode

    # Section-only mode — validate before headless check so bad sections always error
    if section is not None:
        if section not in _SECTION_KEYS:
            valid = ", ".join(_SECTION_KEYS)
            click.echo(f"Unknown section: '{section}'. Valid sections: {valid}", err=True)
            raise SystemExit(1)
        from superharness.ui.prompts import is_interactive_stdin
        _is_headless = non_interactive or not is_interactive_stdin()
        for key, _label, func in ONBOARD_SECTIONS:
            if key == section:
                func(project_path, config, _is_headless)
                _write_profile(project_path, config)
                click.echo(f"\n[{section}] configuration complete.")
                return

    # Headless / intro banner — suppressed in quick mode
    from superharness.ui.prompts import is_interactive_stdin
    if not quick and (non_interactive or not is_interactive_stdin()):
        _print_noninteractive_guidance(project_path)
    elif not quick and _is_returning_user(project_path):
        click.echo("")
        click.echo("Existing superharness project detected.")
        click.echo("  Quick setup / Full setup / Section-only available.")
        click.echo("  Run 'shux onboard --section <name>' to reconfigure a single section.")
        click.echo("  Continuing with full setup...")

    # Full run — load state (includes version-migration) then execute each step.
    # In quick mode, completed steps are silently bypassed (no "[skip]" noise).
    state = _load_state(sh)

    def _should_run(step: str) -> bool:
        """Return False only when quick mode is active and the step is already done."""
        return not (quick and _is_completed(state, step))

    if _should_run("detect"):
        _step_detect(project_path, state)
    if _should_run("init"):
        _step_init(project_path, state)
    if _should_run("global_claude"):
        _step_global_claude_md(state)
    if _should_run("git_track"):
        _step_git_track(project_path, state, config.get("git_mode", "team"))
    if _should_run("doctor"):
        _step_doctor(project_path, state)

    task_id = None
    if _should_run("task"):
        task_id = _step_task(project_path, state, task_title)
    if _should_run("delegate"):
        _step_delegate(project_path, state, enqueue, task_id)

    # Interactive configuration sections — run after infrastructure steps.
    # Skipped when headless (CI / piped stdin / --non-interactive) so they
    # never block automation. In quick mode the sections still run because
    # the user explicitly asked for a fast reconfigure pass.
    _is_headless = non_interactive or not is_interactive_stdin()
    if not _is_headless:
        click.echo("")
        for key, _label, func in ONBOARD_SECTIONS:
            func(project_path, config, non_interactive=False)
        _write_profile(project_path, config)

    # Summary always runs — shows per-step status table.
    _step_summary(project_path, state)
    _save_state(sh, state)
    _write_profile(project_path, config)

    # Step 8: Behavioral profile bootstrap (Iteration 4)
    _bootstrap_behavioral_profile(project_path, non_interactive)


# ---------------------------------------------------------------------------
# Step 8: behavioral profile bootstrap
# ---------------------------------------------------------------------------

def _bootstrap_behavioral_profile(project_path: str, non_interactive: bool) -> None:
    """Seed the behavioral profile with onboarding answers (cold-start fix)."""
    import json as _json
    upath = os.path.join(os.path.expanduser("~"), ".config", "superharness", "behavioral")
    os.makedirs(upath, exist_ok=True)

    bootstrap = {
        "task_style": {"default_effort": "medium", "tdd_required": True, "confidence": "seed", "sample_count": 0},
    }

    if not non_interactive:
        click.echo("")
        click.secho("Behavioral Profile (optional)", fg="cyan", bold=True)
        click.echo("The system learns your patterns automatically. Seed it with 2 quick answers:")
        click.echo("")

        ans = click.prompt("  1. Review style? (strict/balanced/lenient)", default="balanced", show_default=True)
        bootstrap["review_style"] = {"strictness": {"strict": 0.8, "balanced": 0.5, "lenient": 0.3}.get(ans, 0.5), "confidence": "seed", "sample_count": 0}

        ans2 = click.prompt("  2. Communication style? (direct/detailed/concise)", default="direct", show_default=True)
        bootstrap["communication"] = {"style": ans2, "confidence": "seed", "sample_count": 0}

    bootstrap_path = os.path.join(upath, "_bootstrap.json")
    with open(bootstrap_path, "w") as f:
        _json.dump(bootstrap, f, indent=2)

    # Also save task_style seed for immediate use
    task_path = os.path.join(upath, "task_style.json")
    if not os.path.exists(task_path):
        with open(task_path, "w") as f:
            _json.dump(bootstrap["task_style"], f, indent=2)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

@click.command(name="onboard")
@click.option("--project", default=None, help="Project directory (default: cwd)")
@click.option("--non-interactive", "non_interactive", is_flag=True, default=False)
@click.option("--quick", "--quick-setup", "quick", is_flag=True, default=False,
              help="Skip already-completed steps silently; run only pending ones.")
@click.option("--git-mode", "git_mode", type=click.Choice(["team", "solo"]), default="team")
@click.option("--task-title", "task_title", default=None)
@click.option("--enqueue", is_flag=True, default=False)
@click.option("--section", default=None,
              help=f"Run a single section: {', '.join(_SECTION_KEYS)}")
def cmd_onboard(
    project: Optional[str],
    non_interactive: bool,
    quick: bool,
    git_mode: str,
    task_title: Optional[str],
    enqueue: bool,
    section: Optional[str],
) -> None:
    """Interactive (or non-interactive) setup wizard for a new project."""
    project_path = Path(project).resolve() if project else Path.cwd()
    _run_onboard_wizard(
        project_path=project_path,
        non_interactive=non_interactive,
        git_mode=git_mode,
        task_title=task_title,
        enqueue=enqueue,
        section=section,
        quick=quick,
    )


if __name__ == "__main__":
    cmd_onboard()
