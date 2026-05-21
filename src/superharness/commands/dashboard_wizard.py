"""dashboard_wizard.py — pre-launch setup wizard for shux dashboard.

Follows the setup-wizard-pattern (see vault: notes/1_ai/wizard_and_demo/setup-wizard-pattern.md):
  - Curses arrow-key menus with numbered-input fallback
  - First-time vs returning-user flows
  - Idempotent: shows current value, Enter keeps it
  - TTY-aware: prints guidance when headless
  - Sections: Project, Workflow, Agents, First Task
  - Summary at end, then dashboard launches
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import yaml

import logging
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Print primitives
# ---------------------------------------------------------------------------

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def print_header(title: str) -> None:
    print(f"\n{_c('35;1', f'◆ {title}')}")

def print_info(text: str) -> None:
    print(f"  {_c('36', text)}")

def print_success(text: str) -> None:
    print(f"  {_c('32', f'✓ {text}')}")

def print_warning(text: str) -> None:
    print(f"  {_c('33', f'⚠ {text}')}")

def print_error(text: str) -> None:
    print(f"  {_c('31', f'✗ {text}')}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Input primitives
# ---------------------------------------------------------------------------

def is_interactive() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def prompt(question: str, default: str | None = None, password: bool = False) -> str:
    hint = f" [{default}]" if default is not None else ""
    label = _c("36", f"  {question}{hint}: ")
    try:
        if password:
            import getpass
            val = getpass.getpass(label)
        else:
            val = input(label)
        return val.strip() or (default or "")
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)


def prompt_yes_no(question: str, default: bool = True) -> bool:
    yn = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            raw = input(_c("36", f"  {question} {yn}: ")).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)
        if not raw:
            return default
        if raw in ("y", "yes"):
            return True
        if raw in ("n", "no"):
            return False
        print("  Please enter y or n.")


def _curses_menu(question: str, choices: list[str], default: int) -> int:
    """Arrow-key menu. Returns selected index, or -1 on failure/unavailable."""
    try:
        import curses as _curses
    except ImportError:
        return -1

    result: list[int] = [-1]

    def _inner(stdscr: "_curses.window") -> None:
        _curses.curs_set(0)
        _curses.start_color()
        _curses.use_default_colors()
        _curses.init_pair(1, _curses.COLOR_GREEN, -1)
        idx = default

        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            stdscr.addnstr(0, 0, question, w - 1, _curses.A_BOLD)
            for i, choice in enumerate(choices):
                y = i + 2
                if y >= h:
                    break
                if choice == "---":
                    stdscr.addnstr(y, 0, "  ─────────────────────", w - 1)
                    continue
                if i == idx:
                    line = f"  → {choice}"
                    stdscr.addnstr(y, 0, line[:w - 1], w - 1, _curses.color_pair(1) | _curses.A_BOLD)
                else:
                    stdscr.addnstr(y, 0, f"    {choice}", w - 1)
            stdscr.refresh()

            key = stdscr.getch()
            if key in (_curses.KEY_UP, ord("k")):
                # skip separators
                new = (idx - 1) % len(choices)
                while choices[new] == "---":
                    new = (new - 1) % len(choices)
                idx = new
            elif key in (_curses.KEY_DOWN, ord("j")):
                new = (idx + 1) % len(choices)
                while choices[new] == "---":
                    new = (new + 1) % len(choices)
                idx = new
            elif key in (10, 13, _curses.KEY_ENTER):
                result[0] = idx
                return
            elif key in (ord("q"), 27):  # q or Esc
                result[0] = default
                return

    try:
        _curses.wrapper(_inner)
    except Exception as e:
        logger.warning("dashboard_wizard.py unexpected error: %s", e, exc_info=True)
        return -1
    return result[0]


def prompt_choice(question: str, choices: list[str], default: int = 0) -> int:
    """Curses arrow-key menu with numbered fallback. Returns index."""
    idx = _curses_menu(question, choices, default)
    if idx >= 0:
        if idx == default:
            print_info("Skipped (keeping current)")
        return idx

    # Fallback: numbered text input
    print(f"\n  {question}")
    for i, c in enumerate(choices):
        if c == "---":
            print("  ─────────────")
            continue
        marker = " (default)" if i == default else ""
        print(f"  {i + 1}) {c}{marker}")
    try:
        raw = input(_c("36", f"  Select [1-{len(choices)}] (Enter = {default + 1}): ")).strip()
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)
    if not raw:
        print_info("Skipped (keeping current)")
        return default
    if raw.isdigit() and 1 <= int(raw) <= len(choices):
        return int(raw) - 1
    return default


# ---------------------------------------------------------------------------
# Profile helpers (shared with workflow_cmd)
# ---------------------------------------------------------------------------

def _profile_path(project_dir: str) -> Path:
    return Path(project_dir) / ".superharness" / "profile.yaml"


def _load_profile(project_dir: str) -> dict:
    p = _profile_path(project_dir)
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception as e:
        logger.warning("dashboard_wizard.py unexpected error: %s", e, exc_info=True)
        return {}


def _save_profile(project_dir: str, doc: dict) -> None:
    _profile_path(project_dir).write_text(
        yaml.dump(doc, default_flow_style=False, sort_keys=False)
    )


def _task_count(project_dir: str) -> int:
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        init_db(conn)
        row = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()
        conn.close()
        return row[0] if row else 0
    except Exception as e:
        logger.warning("dashboard_wizard.py unexpected error: %s", e, exc_info=True)
        return 0


def _is_first_time(project_dir: str) -> bool:
    from superharness.utils.paths import is_project_initialized
    return not is_project_initialized(project_dir) or _task_count(project_dir) == 0


# ---------------------------------------------------------------------------
# Section 1 — Project
# ---------------------------------------------------------------------------

_STACKS = ["Python", "Node.js", "TypeScript", "Rust", "Go", "Ruby", "Bash", "Other"]
_STATUSES = ["greenfield", "active", "maintenance", "legacy"]


def setup_project(project_dir: str) -> None:
    print_header("Project Setup")
    sh = Path(project_dir) / ".superharness"

    from superharness.utils.paths import is_project_initialized
    if is_project_initialized(project_dir):
        print_success(f".superharness/ already initialized at {project_dir}")
        if not prompt_yes_no("Re-run init?", default=False):
            return

    # Detect defaults
    def _detect_stack() -> str:
        p = Path(project_dir)
        if (p / "pyproject.toml").exists() or (p / "setup.py").exists():
            return "Python"
        if (p / "package.json").exists():
            ts = (p / "tsconfig.json").exists()
            return "TypeScript" if ts else "Node.js"
        if (p / "Cargo.toml").exists():
            return "Rust"
        if (p / "go.mod").exists():
            return "Go"
        if (p / "Gemfile").exists():
            return "Ruby"
        return "Bash"

    detected_stack = _detect_stack()
    default_name = Path(project_dir).name

    name = prompt("Project name", default=default_name)

    stack_idx = prompt_choice(
        "Stack:",
        _STACKS,
        default=_STACKS.index(detected_stack) if detected_stack in _STACKS else 0,
    )
    stack = _STACKS[stack_idx]

    status_idx = prompt_choice("Project status:", _STATUSES, default=0)
    status = _STATUSES[status_idx]

    py = sys.executable
    src_root = Path(__file__).resolve().parent.parent.parent.parent
    env = {**os.environ, "PYTHONPATH": str(src_root / "src")}

    result = subprocess.run(
        [py, "-m", "superharness.commands.init_project", "--skip-hooks", name, stack, status],
        env=env, cwd=project_dir, capture_output=True, text=True,
    )
    for line in result.stdout.splitlines():
        s = line.strip()
        if s.startswith("Created:") or s.startswith("Done"):
            print_success(s.removeprefix("Created:").strip())
    if result.returncode != 0:
        print_warning("init exited non-zero — project may already be initialized")


# ---------------------------------------------------------------------------
# Section 2 — Workflow Policy
# ---------------------------------------------------------------------------

_AUTONOMY = ("ai_driven", "oversight", "hands_on")
_AUTONOMY_LABELS = {
    "ai_driven": "AI does everything — auto-approves plans, dispatches itself",
    "oversight":  "AI works, you approve plans and close tasks",
    "hands_on":   "AI works, you gate every transition manually",
}
_PRESETS = ("implementation", "quick", "discussion", "review", "approval", "note")
_PRESET_LABELS = {
    "implementation": "TDD-friendly, full lifecycle",
    "quick":          "todo → in_progress → done",
    "discussion":     "async discussion flow",
    "review":         "peer review cycle",
    "approval":       "explicit approval gate",
    "note":           "documentation only",
}


def setup_workflow(project_dir: str) -> None:
    print_header("Workflow Policy")
    profile = _load_profile(project_dir)
    wf = profile.get("workflow") or {}

    current_autonomy = profile.get("autonomy") or "ai_driven"
    current_preset = wf.get("default_preset") or "implementation"
    current_tdd = bool(wf.get("require_tdd", True))

    print_info(f"Current: autonomy={current_autonomy}  preset={current_preset}  tdd={current_tdd}")

    # Autonomy
    a_choices = [f"{k}  —  {_AUTONOMY_LABELS[k]}" for k in _AUTONOMY]
    a_choices.append("Keep current")
    a_default = list(_AUTONOMY).index(current_autonomy) if current_autonomy in _AUTONOMY else len(_AUTONOMY)
    a_idx = prompt_choice("Who drives this project's task flow?", a_choices, default=a_default)
    if a_idx < len(_AUTONOMY):
        profile["autonomy"] = _AUTONOMY[a_idx]

    # Preset
    p_choices = [f"{k}  —  {_PRESET_LABELS[k]}" for k in _PRESETS]
    p_choices.append("Keep current")
    p_default = list(_PRESETS).index(current_preset) if current_preset in _PRESETS else len(_PRESETS)
    p_idx = prompt_choice("Default workflow preset for new tasks?", p_choices, default=p_default)
    if p_idx < len(_PRESETS):
        profile.setdefault("workflow", {})["default_preset"] = _PRESETS[p_idx]

    # TDD
    tdd = prompt_yes_no("Require TDD red/green/refactor in plan handoffs?", default=current_tdd)
    profile.setdefault("workflow", {})["require_tdd"] = tdd

    _save_profile(project_dir, profile)
    print_success("Workflow policy saved to .superharness/profile.yaml")


# ---------------------------------------------------------------------------
# Section 3 — Agents
# ---------------------------------------------------------------------------

_ALL_AGENTS = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
_AGENT_LABELS = {
    "claude-code":  "Claude Code (Anthropic)",
    "codex-cli":    "Codex CLI (OpenAI)",
    "gemini-cli":   "Gemini CLI (Google)",
    "opencode":     "opencode (open-source)",
}


def setup_agents(project_dir: str) -> None:
    print_header("Agents")
    profile = _load_profile(project_dir)
    current = profile.get("agents", {}).get("enabled") or _ALL_AGENTS[:]

    print_info(f"Currently enabled: {', '.join(current)}")

    choices = [f"{_AGENT_LABELS[a]}" for a in _ALL_AGENTS] + ["Keep current"]
    print()
    print("  Which agents can work on this project? (toggle — separate question per agent)")

    enabled: list[str] = []
    for agent in _ALL_AGENTS:
        label = _AGENT_LABELS[agent]
        is_on = agent in current
        if prompt_yes_no(f"Enable {label}?", default=is_on):
            enabled.append(agent)

    if not enabled:
        print_warning("No agents selected — keeping previous list")
        return

    profile.setdefault("agents", {})["enabled"] = enabled
    _save_profile(project_dir, profile)
    print_success(f"Agents saved: {', '.join(enabled)}")


# ---------------------------------------------------------------------------
# Section 4 — First Task
# ---------------------------------------------------------------------------

def setup_first_task(project_dir: str) -> None:
    print_header("First Task")

    n = _task_count(project_dir)
    if n > 0:
        print_info(f"{n} task(s) already exist — skipping first-task setup")
        return

    print_info("No tasks yet. Create one now to get started.")
    if not prompt_yes_no("Create a task?", default=True):
        return

    task_id = prompt("Task ID (slug, e.g. feat.hello-world)", default="feat.my-first-task")
    title = prompt("Title", default="My first task")

    profile = _load_profile(project_dir)
    enabled_agents = profile.get("agents", {}).get("enabled") or _ALL_AGENTS
    agent_choices = enabled_agents + ["Skip (set owner later)"]
    owner_idx = prompt_choice("Assign to agent:", agent_choices, default=0)
    owner = enabled_agents[owner_idx] if owner_idx < len(enabled_agents) else "claude-code"

    py = sys.executable
    src_root = Path(__file__).resolve().parent.parent.parent.parent
    env = {**os.environ, "PYTHONPATH": str(src_root / "src")}

    result = subprocess.run(
        [py, "-m", "superharness.commands.task", "create",
         "--project", project_dir,
         "--id", task_id,
         "--title", title,
         "--owner", owner],
        env=env, capture_output=True, text=True,
    )
    if result.returncode == 0:
        print_success(f"Task '{task_id}' created and assigned to {owner}")
    else:
        print_warning(f"Task creation failed: {result.stderr.strip() or result.stdout.strip()}")


# ---------------------------------------------------------------------------
# Section registry
# ---------------------------------------------------------------------------

SETUP_SECTIONS = [
    ("project",  "Project Setup",    setup_project),
    ("workflow", "Workflow Policy",  setup_workflow),
    ("agents",   "Agents",           setup_agents),
    ("task",     "First Task",       setup_first_task),
]


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(project_dir: str) -> None:
    print()
    print(_c("35;1", "  ══════════════════════════════════"))
    print(_c("35;1", "  ◆ Configuration Summary"))
    print(_c("35;1", "  ══════════════════════════════════"))

    profile = _load_profile(project_dir)
    wf = profile.get("workflow") or {}
    agents = profile.get("agents", {}).get("enabled") or _ALL_AGENTS

    autonomy = profile.get("autonomy") or "ai_driven"
    preset   = wf.get("default_preset") or "implementation"
    tdd      = bool(wf.get("require_tdd", True))
    n_tasks  = _task_count(project_dir)

    print_info(f"Project dir : {project_dir}")
    print_info(f"Autonomy    : {autonomy}  — {_AUTONOMY_LABELS.get(autonomy, '')}")
    print_info(f"Preset      : {preset}")
    print_info(f"Require TDD : {tdd}")
    print_info(f"Agents      : {', '.join(agents)}")
    print_info(f"Tasks       : {n_tasks}")
    print()
    print_info("Launching dashboard…")


# ---------------------------------------------------------------------------
# Non-interactive guidance
# ---------------------------------------------------------------------------

def _print_headless_guidance(project_dir: str) -> None:
    print(_c("33", "\n  ⚠ Dashboard wizard — non-interactive mode"))
    print_info("Configure with:")
    print_info("  shux workflow --autonomy oversight")
    print_info("  shux workflow --default-preset quick")
    print_info("  shux task create --project . --id <id> --title '...' --owner claude-code")
    print_info("")
    print_info("Re-run in an interactive terminal for the full wizard:")
    print_info("  shux dashboard --wizard")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    print()
    print(_c("35;1", "  ╔══════════════════════════════════════╗"))
    print(_c("35;1", "  ║   superharness  Setup Wizard          ║"))
    print(_c("35;1", "  ╚══════════════════════════════════════╝"))
    print()


def _run_quick_setup(project_dir: str) -> None:
    """Prompt only for what is actually missing."""
    sh = Path(project_dir) / ".superharness"
    profile = _load_profile(project_dir)
    missing: list[tuple[str, str, Callable]] = []

    from superharness.utils.paths import is_project_initialized
    if not is_project_initialized(project_dir):
        missing.append(("project", "Project Setup", setup_project))
    if not profile.get("autonomy"):
        missing.append(("workflow", "Workflow Policy", setup_workflow))
    if not profile.get("agents", {}).get("enabled"):
        missing.append(("agents", "Agents", setup_agents))
    if _task_count(project_dir) == 0:
        missing.append(("task", "First Task", setup_first_task))

    if not missing:
        print_success("Everything is configured!")
        return

    print_info(f"Missing: {', '.join(label for _, label, _ in missing)}")
    for _, label, fn in missing:
        fn(project_dir)


def run_wizard(project_dir: str, section: str | None = None, force: bool = False) -> None:
    """Entry point called by _run_dashboard in cli.py.

    Args:
        project_dir: absolute project path
        section: run only this section key (e.g. "workflow")
        force: run wizard even if already configured
    """
    if not is_interactive():
        _print_headless_guidance(project_dir)
        return

    # Section-only mode: shux dashboard --setup workflow
    if section:
        for key, label, fn in SETUP_SECTIONS:
            if key == section:
                print_header(label)
                fn(project_dir)
                _print_summary(project_dir)
                return
        print_error(f"Unknown section: {section}. Valid: {', '.join(k for k, _, _ in SETUP_SECTIONS)}")
        return

    _print_banner()

    first_time = force or _is_first_time(project_dir)

    if first_time:
        # First-time flow: linear walkthrough
        print(_c("2", "  We'll walk you through:"))
        for i, (_, label, _) in enumerate(SETUP_SECTIONS, 1):
            print(_c("2", f"    {i}. {label}"))
        print()
        try:
            input(_c("36", "  Press Enter to begin, or Ctrl+C to skip wizard… "))
        except (KeyboardInterrupt, EOFError):
            print("\n  Wizard skipped.")
            return

        for _, _, fn in SETUP_SECTIONS:
            fn(project_dir)

    else:
        # Returning user: menu
        menu = [
            "Quick Setup — configure missing items only",
            "Full Setup — reconfigure everything",
            "---",
        ] + [label for _, label, _ in SETUP_SECTIONS] + [
            "---",
            "Launch dashboard (skip wizard)",
        ]
        choice = prompt_choice("What would you like to do?", menu, default=0)

        label_to_fn = {label: fn for _, label, fn in SETUP_SECTIONS}
        selected = menu[choice] if choice < len(menu) else menu[-1]

        if selected == "Quick Setup — configure missing items only":
            _run_quick_setup(project_dir)
        elif selected == "Full Setup — reconfigure everything":
            for _, _, fn in SETUP_SECTIONS:
                fn(project_dir)
        elif selected in label_to_fn:
            label_to_fn[selected](project_dir)
        elif selected in ("Launch dashboard (skip wizard)", "---"):
            return  # skip straight to dashboard

    _print_summary(project_dir)
