"""
superharness CLI — thin Python entry point; all commands route to Python modules.
Cross-platform: macOS, Linux, Windows.
"""
from __future__ import annotations

import importlib.resources as _importlib_resources
import os
import subprocess
import sys

import click

from superharness import __version__
from superharness.engine.adapter_registry import fallback_flagship, flagship
from superharness.logging_utils import get_logger as _bootstrap_logger

import logging
_logger = logging.getLogger(__name__)

# Bootstrap the central logger once so every `logging.getLogger("superharness.*")`
# call in any module propagates to the rotating file handler. Modules don't
# need to know the logger exists — stdlib hierarchy does the routing.
_bootstrap_logger("superharness").debug("cli bootstrap")

# Model shorthand → full model ID used by `shux run --model <shorthand>`.
# "opus" resolves to the current-generation max-tier model.
# Override via env vars: SUPERHARNESS_MODEL_SONNET, _HAIKU, _OPUS.
MODEL_SHORTCUTS: dict[str, str] = {
    "sonnet":    os.environ.get("SUPERHARNESS_MODEL_SONNET", "claude-sonnet-4-6"),
    "haiku":     os.environ.get("SUPERHARNESS_MODEL_HAIKU", "claude-haiku-4-5-20251001"),
    "opus":      os.environ.get("SUPERHARNESS_MODEL_OPUS", flagship()),
    "opus-4-8":  os.environ.get("SUPERHARNESS_MODEL_OPUS", flagship()),
    "opus-4-7":  fallback_flagship(),  # version pin
    "opus-4-6":  fallback_flagship(),  # alias — same cost, route to latest stable
}

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = str(_importlib_resources.files("superharness").joinpath("scripts"))
_ROOT = os.path.dirname(os.path.dirname(_PACKAGE_DIR))  # repo root (editable installs / shux update)


def _inject_quickstart(help_text: str) -> str:
    """Insert onboarding quickstart before the Commands section.

    Shows a cold-start banner ('New here? Run shux onboard') when .superharness/
    is absent from the current directory — i.e. the user hasn't set up this project yet.
    """
    lines = help_text.split("\n")
    insert_idx = next((i for i, line in enumerate(lines) if line.startswith("Commands:")), len(lines))

    has_superharness = os.path.isdir(os.path.join(os.getcwd(), ".superharness"))

    if not has_superharness:
        quickstart = [
            "",
            "New here?  →  shux onboard",
            "  Guided setup wizard — runs in under 3 minutes, sets up your project,",
            "  writes AGENTS.md so Claude Code / Codex know to use superharness.",
            "",
            "  shux explain   # What is superharness? (10-second answer)",
            "  shux onboard   # Interactive setup wizard",
            "  shux demo      # Zero-config sandbox walkthrough",
            "",
        ]
    else:
        quickstart = [
            "",
            "Quick Start — First Commands:",
            "  shux contract          # View all tasks",
            "  shux delegate <id>     # Hand a task to an agent",
            "  shux doctor            # Check prerequisites",
            "  shux dashboard         # Open browser dashboard",
            "",
        ]
    return "\n".join(lines[:insert_idx] + quickstart + lines[insert_idx:])


class _OnboardingGroup(click.Group):
    """Group that injects the first-commands quickstart into --help output."""

    def get_help(self, ctx: click.Context) -> str:  # noqa: D401
        return _inject_quickstart(super().get_help(ctx))


def _run_script(script: str, args: tuple) -> None:
    """Run a shell script and exit with its return code."""
    path = os.path.join(_SCRIPTS, script)
    result = subprocess.run(["bash", path] + list(args))
    sys.exit(result.returncode)


def _run_module(module: str, args: tuple) -> None:
    """Run a Python command module and exit with its return code."""
    result = subprocess.run([sys.executable, "-m", module] + list(args))
    sys.exit(result.returncode)


@click.group(
    cls=_OnboardingGroup,
    invoke_without_command=True,
    context_settings={"help_option_names": ["--help", "-h"]},
)
@click.version_option(__version__, "-v", "--version", prog_name="superharness")
@click.pass_context
def main(ctx):
    """superharness — multi-agent session handoff framework."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


def _cmd(name: str, help_text: str, module: str | None = None, script: str | None = None):
    """Factory: register a passthrough subcommand."""
    @main.command(name=name, context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []}, help=help_text)
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def _handler(args):
        if module:
            _run_module(module, args)
        else:
            _run_script(script, args)  # type: ignore[arg-type]
    _handler.__name__ = f"cmd_{name.replace('-', '_')}"
    return _handler


# ── Python command modules ──────────────────────────────────────────────────

@main.command(name="contract", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_contract(args):
    """Show active contract summary."""
    if "--validate" in args or (args and args[0] == "validate"):
        _run_module("superharness.commands.contract_validate", args[1:] if args and args[0] == "validate" else args)
        return
    # Drop legacy 'today' subcommand token for backward compatibility
    filtered = tuple(a for a in args if a not in ("today", "help"))
    _run_module("superharness.commands.contract_today", filtered)
_cmd("continue",        "Resume the active contract: next resumable task + recommended action.", module="superharness.commands.continue_cmd")
_cmd("task",            "Create/delete contract tasks.",              module="superharness.commands.task")
_cmd("dispatch",        "Dispatch next inbox item.",                  module="superharness.commands.inbox_dispatch")
_cmd("watch",           "Run one watch cycle or foreground loop.",    module="superharness.commands.inbox_watch")
_cmd("discuss",         "Approval-gated consensus helpers.",         module="superharness.commands.discuss")
_cmd("discussion",      "Alias for 'discuss'.",                      module="superharness.commands.discuss")
_cmd("enqueue",         "Add inbox item.",                           module="superharness.commands.inbox_enqueue")
_cmd("normalize",       "Normalize/archive inbox rows.",             module="superharness.commands.inbox_normalize")
_cmd("inbox-gc",        "Reconcile stale inbox items against contract.", module="superharness.commands.inbox_gc")
_cmd("worktree-gc",     "Clean orphaned dispatch worktrees.",           module="superharness.commands.worktree_gc")
_cmd("worktree",        "Manage git worktrees (list/create/remove/gc).", module="superharness.commands.worktree")
_cmd("notify-desktop",  "Send native desktop notification.",            module="superharness.commands.notify_desktop")
_cmd("recap",           "What happened in the last N hours.",           module="superharness.commands.recap")
_cmd("recover",         "Recover stale launched items.",             module="superharness.commands.inbox_recover")
_cmd("doctor",          "Check local setup and project health.",     module="superharness.commands.doctor")
_cmd("pipeline-check",  "Probe the auto-mode pipeline for issues.",  module="superharness.commands.pipeline_check")
_cmd("backup-state",    "Backup or restore the SQLite state DB.",   module="superharness.commands.backup_state")
_cmd("archive-yaml",    "Archive YAML state or export SQLite snapshot.", module="superharness.commands.archive_yaml")
_cmd("export-yaml",     "Export YAML snapshot from SQLite state.",       module="superharness.commands.yaml_io")
_cmd("import-yaml",     "Import YAML state files into SQLite.",          module="superharness.commands.yaml_io")
_cmd("uninstall",       "Remove system-level artifacts.",            module="superharness.commands.uninstall")
_cmd("status",          "Show watcher and inbox health summary.",    module="superharness.commands.status")
_cmd("rules",           "List, show, or search project rules.",      module="superharness.commands.rules")
_cmd("notify",          "Send alerts for watcher/retry issues.",     module="superharness.commands.notify")
_cmd("install-wrapper", "Symlink superharness into PATH.",           module="superharness.commands.install_wrapper")
_cmd("recall",          "Search handoffs and ledger by keyword.",    module="superharness.engine.recall")
_cmd("insights",        "Task/dispatch/agent analytics from SQLite.", module="superharness.commands.insights")
_cmd("hygiene",         "Check contract hygiene.",                   module="superharness.engine.validate")

# ── Fully ported Python command modules (cross-platform) ─────────────────────

_cmd("tui",             "Terminal board — live task view with keyboard actions.", module="superharness.commands.tui")
_cmd("init",            "Initialize project protocol files.",        module="superharness.commands.init_project")
_cmd("logs",            "Show or tail the centralized superharness log.", module="superharness.commands.logs")
_cmd("watcher-worker",  "Build watcher worker and install watcher.", module="superharness.commands.watcher_worker")
_cmd("heartbeat",       "Run proactive watcher checks.",             module="superharness.commands.heartbeat")
_cmd("agent-pulse",     "Write/read agent liveness signal (Phase 2 heartbeat).", module="superharness.commands.agent_pulse")
_cmd("pulse",           "Register agent liveness in SQLite (agent_heartbeats).", module="superharness.commands.pulse_cmd")
_cmd("artifact",        "Manage task artifacts (add/list files produced by agents).", module="superharness.commands.artifact_cmd")
_cmd("auto-dispatch",   "Scan todo tasks, classify, and enqueue to best agent.", module="superharness.commands.auto_dispatch")
_cmd("schedule",        "Cron-like scheduled task dispatch (add/list/remove/run).", module="superharness.commands.schedule")
_cmd("demo",            "Zero-config task lifecycle walkthrough.",   module="superharness.commands.demo")
_cmd("test-type",       "Set mandatory test types on a task.",       module="superharness.commands.test_type")
_cmd("verify",          "Record verification result for a task.",   module="superharness.commands.verify")
_cmd("close",           "Close a verified task (done + ledger).",   module="superharness.commands.close")
_cmd("context",         "Show full context for a task (handoff, decisions, failures, ledger, git).", module="superharness.commands.context")
_cmd("install-hooks",   "Merge adapter hooks into ~/.claude/settings.json (portable, no hardcoded paths).", module="superharness.commands.install_hooks")
_cmd("enhance",         "Module marketplace — enable, disable, list integrations.", module="superharness.commands.enhance")
_cmd("adapters",        "List, inspect, and validate agent runtime adapters.",      module="superharness.commands.adapters")
_cmd("pack",            "Export and import portable project state.",               module="superharness.commands.pack")
_cmd("benchmark",       "Show dispatch cost and duration leaderboard.",            module="superharness.commands.benchmark")
_cmd("diff",            "Preview agent changes for a task before closing.",        module="superharness.commands.diff")
_cmd("adapter-payload", "Emit project state as stable JSON payload (schema v1.0).", module="superharness.commands.adapter_payload")
_cmd("handoff-write",   "Author a plan or report handoff YAML (adapter-safe).",     module="superharness.commands.handoff_write")
_cmd("handoff-generate", "Generate a structured handoff from task state.",           module="superharness.commands.handoff_generate")
_cmd("handoff",         "Handoff subcommand group (write).",                        module="superharness.commands.handoff_write")
_cmd("subtask-cancel",  "Mark a subtask cancelled with a mandatory reason.",        module="superharness.commands.subtask_cancel")
_cmd("approve",         "Approve a task's pending plan (writes operator_command row; idempotent).", module="superharness.commands.approve")
_cmd("reject",          "Reject a task's pending plan (writes operator_command row; idempotent).",  module="superharness.commands.approve")

# profile runs in-process (no subprocess) so output is captured correctly
def _register_profile():
    try:
        import click as _click
        @_click.command("profile", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
        @_click.argument("args", nargs=-1, type=_click.UNPROCESSED)
        def profile_cmd(args):
            """View and manage your learned behavioral profile."""
            from superharness.commands.profile_cmd import cmd_profile
            cmd_profile(list(args))
        main.add_command(profile_cmd)
    except Exception as e:
        _logger.warning("Failed to register profile command: %s", e)

_register_profile()

# memory-roots runs in-process (same reason as profile)
def _register_memory_roots():
    try:
        import click as _click
        @_click.command("memory-roots", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
        @_click.argument("args", nargs=-1, type=_click.UNPROCESSED)
        def memory_roots_cmd(args):
            """Manage project root directories for cross-project memory scanning."""
            from superharness.commands.memory_cmd import cmd_memory_roots
            cmd_memory_roots(list(args))
        main.add_command(memory_roots_cmd)
    except Exception as e:
        _logger.warning("Failed to register memory-roots command: %s", e)

_register_memory_roots()

# operator-memory and operator-forget run in-process (need argparse, not module passthrough)
def _register_operator_memory():
    try:
        from superharness.commands.operator_memory_cli import cmd_operator_memory, cmd_operator_forget
        import click as _click

        @_click.command("operator-memory", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
        @_click.argument("args", nargs=-1, type=_click.UNPROCESSED)
        def _om_cmd(args):
            """Show operator memory (learned failure patterns)."""
            cmd_operator_memory(list(args))

        @_click.command("operator-forget", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
        @_click.argument("args", nargs=-1, type=_click.UNPROCESSED)
        def _of_cmd(args):
            """Forget a learned failure pattern."""
            cmd_operator_forget(list(args))

        main.add_command(_om_cmd)
        main.add_command(_of_cmd)
    except Exception as e:
        _logger.warning("Failed to register operator-memory commands: %s", e)

_register_operator_memory()

# explain runs in-process (no subprocess) so CliRunner captures output correctly
def _register_explain():
    try:
        from superharness.commands.explain import cmd_explain
        main.add_command(cmd_explain, name="explain")
        main.add_command(cmd_explain, name="why")
        main.add_command(cmd_explain, name="wtf")
    except Exception as e:
        _logger.warning("Failed to register explain commands: %s", e)

_register_explain()

# Daemon is a Click group — import and add directly
def _register_daemon():
    try:
        from superharness.commands.daemon import cmd_daemon
        main.add_command(cmd_daemon)
    except Exception as e:
        _logger.warning("Failed to register daemon commands: %s", e)

_register_daemon()


# MCP server — Click group
def _register_mcp():
    try:
        from superharness.mcp.cli import cmd_mcp
        main.add_command(cmd_mcp)
    except Exception as e:
        _logger.warning("Failed to register MCP commands: %s", e)

_register_mcp()


# onboard runs in-process so CliRunner captures output correctly
def _register_onboard():
    try:
        from superharness.commands.onboard import cmd_onboard
        main.add_command(cmd_onboard)
    except Exception as e:
        _logger.warning("Failed to register onboard command: %s", e)

_register_onboard()


def _register_config():
    try:
        from superharness.commands.config import cmd_config
        main.add_command(cmd_config)
    except Exception as e:
        _logger.warning("Failed to register config command: %s", e)

_register_config()


def _register_observation():
    try:
        from superharness.commands.observation import cmd_observation_group
        main.add_command(cmd_observation_group)
    except Exception as e:
        _logger.warning("Failed to register observation commands: %s", e)

_register_observation()


def _register_workflow():
    try:
        import click as _click

        @_click.command("workflow", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
        @_click.argument("args", nargs=-1, type=_click.UNPROCESSED)
        def workflow_cmd(args):
            """Read/write project-level workflow policy (autonomy, preset, require_tdd)."""
            from superharness.commands.workflow_cmd import cmd_workflow
            cmd_workflow(list(args))

        main.add_command(workflow_cmd)
    except Exception as e:
        _logger.warning("Failed to register workflow command: %s", e)

_register_workflow()


def _register_migrate_state():
    try:
        import click as _click

        @_click.command("migrate-state", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
        @_click.argument("args", nargs=-1, type=_click.UNPROCESSED)
        def migrate_state_cmd(args):
            """Move legacy .superharness/state.sqlite3 to the XDG state path."""
            from superharness.commands.migrate_state import cmd_migrate_state
            cmd_migrate_state(list(args))

        main.add_command(migrate_state_cmd)
    except Exception as e:
        _logger.warning("Failed to register migrate-state command: %s", e)

_register_migrate_state()


# Dashboard commands — extracted to commands/dashboard.py (C4 decomposition)
from superharness.commands.dashboard import register_dashboard_commands, run_dashboard
register_dashboard_commands(main, _SCRIPTS)

# Hidden backwards-compat aliases
@main.command(name="monitor", hidden=True, context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_monitor_compat(args):
    """Backwards-compat alias for 'dashboard'."""
    run_dashboard(args, _SCRIPTS)


@main.command(name="monitor-ui", hidden=True, context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_monitor_ui_compat(args):
    """Backwards-compat alias for 'dashboard-ui'."""
    run_dashboard(args, _SCRIPTS)


@main.command(name="delegate", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_delegate(args):
    """Delegate task to an agent."""
    # Shorthand: `delegate <task-id> [--project P] [--print-only]`
    # Look up the task owner from contract and inject --to and --task.
    if args and not args[0].startswith("-"):
        task_id = args[0]
        rest = list(args[1:])
        # Find --project in rest args
        project_dir = None
        for i, a in enumerate(rest):
            if a in ("--project", "-p") and i + 1 < len(rest):
                project_dir = rest[i + 1]
                break
        if project_dir is None:
            project_dir = os.environ.get("SUPERHARNESS_PROJECT") or os.getcwd()
        # Look up owner from SQLite
        target = None
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import tasks_dao
            _conn = get_connection(project_dir)
            try:
                init_db(_conn)
                _row = tasks_dao.get(_conn, task_id)
                if _row and _row.owner in ("claude-code", "codex-cli"):
                    target = _row.owner
            finally:
                _conn.close()
        except Exception as e:
            print(f"Warning: could not read task owner from state.db: {e}", file=sys.stderr)
        if target is None:
            target = "claude-code"
        new_args = ["--to", target, "--task", task_id] + rest
        _run_module("superharness.commands.delegate", tuple(new_args))
    else:
        _run_module("superharness.commands.delegate", args)


def _is_git_repo(path: str) -> bool:
    r = subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


@main.command(name="update", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_update(args):
    """Pull latest superharness and refresh project templates."""
    if "--help" in args or "-h" in args:
        click.echo("Usage: shux update [OPTIONS]")
        click.echo("\nPull latest superharness and refresh project templates.")
        return
    print("superharness — update")
    print("=====================")
    if _is_git_repo(_ROOT):
        print("Step 1: git pull (updating superharness repo)...")
        r = subprocess.run(["git", "-C", _ROOT, "pull", "--ff-only"])
        if r.returncode != 0:
            sys.exit("git pull failed")
    else:
        # pipx / pip install — upgrade via package manager
        print("Step 1: upgrading superharness package...")
        # Try pipx first, fall back to pip
        pipx_r = subprocess.run(["pipx", "upgrade", "superharness"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if pipx_r.returncode != 0:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--upgrade", "superharness"])
            if r.returncode != 0:
                sys.exit("upgrade failed")
        else:
            print("pipx upgrade superharness — done")
    print()
    print("Step 2: refreshing templates...")
    profile = os.path.join(".superharness", "profile.yaml")
    if os.path.isfile(profile):
        _run_module("superharness.commands.init_project", ("--refresh", "--from-profile", profile) + args)
    else:
        _run_module("superharness.commands.init_project", ("--refresh", "--detect") + args)


@main.command(name="shux")
def cmd_shux():
    """Show shux operator shortcuts."""
    click.echo("""superharness — shux shortcuts
==============================

  shux init                ← bootstrap .superharness/ for this project (interactive)
  shux doctor              ← check prerequisites and protocol health
  shux contract            ← show all tasks with status, owner, next-task suggestion
  shux continue            ← resume active contract and run full session lifecycle
  shux status              ← dashboard: contract, tasks, watcher, profile
  shux dashboard           ← open browser dashboard (auto-detects project, opens browser)
  shux tui                 ← terminal board — live task view with keyboard actions
  shux test-type <id>      ← set mandatory test types for a task (interactive prompt)
  shux enhance             ← list, enable, disable modules (integrations)
  shux run "<prompt>"      ← run a prompt via SDK (auto-detect, falls back to CLI)
  shux delegate <task-id>  ← create task + enqueue in one step for watcher dispatch
  shux verify <task-id>    ← record verification result (pass/fail) before close
  shux close <task-id>     ← mark task done, append ledger, write handoff (requires verify)
  shux context <task-id>   ← show handoff, decisions, failures, and git context
  shux recall <keywords>   ← search past handoffs and ledger entries
  shux hygiene             ← validate protocol compliance (contract, handoffs, ledger)
  shux watch               ← start continuous watcher in foreground
  shux uninstall           ← remove watcher and system artifacts
  shux update              ← git pull + re-run init to refresh templates
  shux discuss <sub>       ← manage discussions and approval gates

Full session flow:
  shux init → shux doctor → shux contract → shux continue → shux close <id>""")


@main.command(name="run", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_run(args):
    """Run a prompt via SDK (auto-detects SDK, falls back to CLI).

    Usage:
      shux run "summarize CLAUDE.md"
      shux run "write tests for cli.py" --model opus
      shux run "fix the bug" --budget 0.50
    """
    import argparse

    p = argparse.ArgumentParser(prog="run")
    p.add_argument("prompt", help="Prompt to send to Claude")
    p.add_argument("--model", default=None, help="Model override (e.g. claude-sonnet-4-6, haiku)")
    p.add_argument("--budget", type=float, default=None, help="Max budget in USD")
    p.add_argument("--timeout", type=int, default=300, help="Timeout in seconds (default: 300)")
    p.add_argument("--project", "-p", default=None, help="Project directory (default: cwd)")
    opts = p.parse_args(list(args))

    project_dir = os.path.realpath(opts.project or os.getcwd())

    # Resolve model shorthand
    model = opts.model
    if model:
        model = MODEL_SHORTCUTS.get(model, model)

    from superharness.engine.sdk_runner import sdk_available, SDKRunner

    if not sdk_available():
        print("SDK not installed. Install with: pip install claude-agent-sdk", file=sys.stderr)
        print("Falling back to CLI...", file=sys.stderr)
        # Fall back to delegate CLI
        delegate_args = ["--to", "claude-code", "--project", project_dir]
        if model:
            delegate_args += ["--model", model]
        delegate_args += ["--via", "cli"]
        _run_module("superharness.commands.delegate", tuple(delegate_args))
        return

    try:
        import threading

        runner = SDKRunner(
            project_dir=__import__("pathlib").Path(project_dir),
            model=model,
            max_budget_usd=opts.budget,
        )

        result_holder: list = []
        exc_holder: list = []

        def _run():
            try:
                result_holder.append(runner.run(opts.prompt))
            except Exception as e:
                exc_holder.append(e)

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=opts.timeout)
        if t.is_alive():
            print(f"\nTimed out after {opts.timeout}s", file=sys.stderr)
            sys.exit(124)
        if exc_holder:
            raise exc_holder[0]

        result = result_holder[0]
        print(result["output"])
        print(f"\n--- tokens: {result['input_tokens']} in, {result['output_tokens']} out | cost: ${result['cost_usd']:.4f} ---", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


@main.command(name="version")
def cmd_version():
    """Show version."""
    click.echo(f"superharness {__version__}")


@main.command(name="help", hidden=True)
@click.pass_context
def cmd_help(ctx):
    """Show help text (alias for --help)."""
    click.echo(ctx.parent.get_help())


@main.group()
def operator():
    """Manage the Superharness stack (Watcher, Dashboard, and Health)."""
    pass


@operator.command(name="check")
@click.option("--project", "-p", default=".", help="Project directory")
def operator_check(project):
    """Check the health of the Superharness stack."""
    from superharness.engine.operator import Operator
    op = Operator(project)
    summary = op.get_summary()
    
    click.echo(f"Project: {summary['project']}")
    click.echo(f"Overall Health: {'✅ OK' if summary['healthy'] else '❌ ISSUES'}")
    
    w = summary['components']['watcher']
    click.echo(f"  Watcher: {'✅' if w['ok'] else '❌'} {w['message']}")
    
    for c in summary['components']['conflicts']:
        click.echo(f"  Conflict: ⚠️ {c['message']}")


@operator.command(name="start")
@click.option("--project", "-p", default=".", help="Project directory")
@click.option("--port", default=8787, help="Dashboard port")
@click.option("--no-open", "no_open", is_flag=True, default=False, help="Do not open browser on start (for daemon/launchd use)")
@click.option("--dashboard", "use_dashboard", is_flag=True, default=False, help="Also start the dashboard UI (opt-in)")
@click.option("--no-daemon", "no_daemon", is_flag=True, default=False,
              help="Run in foreground (for debugging; default detaches)")
def operator_start(project, port, no_open, use_dashboard, no_daemon):
    """Start the Superharness Guardian (Watcher + optional Dashboard).

    By default, daemonizes via fork+setsid so the watcher survives the
    invoking shell session. Use --no-daemon for foreground debugging.
    """
    from superharness.engine.operator import Operator
    op = Operator(project)
    op.start_stack(dashboard_port=port, no_open=no_open, use_dashboard=use_dashboard)
    if use_dashboard:
        click.echo(f"dashboard: http://127.0.0.1:{port}")
    click.echo(f"monitor pid: {os.getpid()}")
    
    if not use_dashboard:
        click.echo("  (watcher cycles every 15s)")
    else:
        click.echo("  (watcher cycles every 15s, dashboard auto-restarts on crash)")

    if no_daemon:
        op.monitor_and_recover()
        return

    # Daemonize: fork+detach so the watcher survives the invoking shell.
    # The parent returns immediately; the child runs the monitor loop.
    pid = os.fork()
    if pid:
        click.echo(f"  daemon pid: {pid}")
        return  # parent exits, CLI returns

    # Child: detach from terminal, close stdio, run monitor
    os.setsid()
    os.chdir(project)
    # Redirect stdio to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    os.close(devnull)
    op.monitor_and_recover()


@operator.command(name="install")
@click.option("--project", "-p", default=".", help="Project directory")
@click.option("--all", "install_all", is_flag=True, default=False,
              help="Install the operator for ALL opted-in projects (.superharness/persistent marker required)")
@click.option("--force", is_flag=True, default=False,
              help="Allow --all to run non-interactively (e.g. in scripts). Never pass this from an agent.")
@click.option("--dashboard", "use_dashboard", is_flag=True, default=False,
              help="Also start the dashboard UI in the installed service")
@click.option("--watchdog/--no-watchdog", default=True,
              help="Install a 5-min watchdog plist that re-heals the operator on every tick")
def operator_install(project, install_all, force, use_dashboard, watchdog):
    """Install the Guardian as a persistent system service.

    Aggressively removes any stale `com.superharness.*` services and
    orphan plists from prior versions before installing, so old layouts
    can never leak into the new install.

    With --all, discovers every opted-in project (.superharness/persistent)
    and installs the operator for each one. Requires an interactive terminal
    unless --force is also passed. --force is intentionally undocumented for
    agent use: agents must never run --all unattended.
    """
    from pathlib import Path
    import hashlib
    import subprocess

    def _install_one(project_dir: Path) -> str:
        """Install the operator for a single project. Returns the label."""
        # 1. Clean stale services + orphan plists from prior versions.
        from superharness.engine.launchd_health import heal as _heal
        pre = _heal(operator_plist=None)
        if pre.fixed_count():
            click.echo(f"  [{project_dir.name}] {pre.summary()}")

        # 2. Run the install script.
        script_path = Path(__file__).parent / "scripts" / "install-operator-service.sh"
        if not script_path.exists():
            script_path = Path(sys.prefix) / "lib" / "python3.11" / "site-packages" / "superharness" / "scripts" / "install-operator-service.sh"
        click.echo(f"  Installing operator for {project_dir}...")
        
        cmd = ["bash", str(script_path), str(project_dir)]
        if use_dashboard:
            cmd.append("--dashboard")
        subprocess.run(cmd, check=True)

        # 3. Self-heal: verify the operator plist is loaded.
        short = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
        operator_label = f"com.superharness.operator.{short}"
        operator_plist = Path.home() / "Library" / "LaunchAgents" / f"{operator_label}.plist"
        post = _heal(operator_plist=operator_plist)
        if post.fixed_count():
            click.echo(f"  [{project_dir.name}] {post.summary()}")
        return operator_label

    if install_all:
        if not force and not sys.stdin.isatty():
            click.echo(
                "ERROR: 'operator install --all' refused to run non-interactively.\n"
                "This command installs a persistent system service for every opted-in project.\n"
                "Run it manually in a terminal. Never invoke it from an agent or script.",
                err=True,
            )
            raise SystemExit(1)
        from superharness.engine.launchd_health import (
            find_all_superharness_projects,
            write_watchdog_plist,
            bootstrap as _bootstrap,
        )
        projects = find_all_superharness_projects()
        if not projects:
            click.echo(
                "No opted-in projects found.\n"
                "To enroll a project: touch .superharness/persistent"
            )
            return
        click.echo(f"Found {len(projects)} opted-in project(s):")
        for p in projects:
            click.echo(f"  {p}")
        click.confirm(f"\nInstall a persistent operator service for each?", abort=True)
        labels = []
        for p in projects:
            try:
                labels.append(_install_one(p))
            except Exception as e:
                click.echo(f"  FAILED for {p}: {e}", err=True)
        click.echo(f"\nInstalled operator for {len(labels)} of {len(projects)} project(s):")
        for label in labels:
            click.echo(f"  {label}")

        # Watchdog: single global plist (already supports auto-discovery).
        if watchdog:
            wp = write_watchdog_plist()
            if _bootstrap(wp):
                click.echo(f"\nWatchdog installed: {wp.name} (heals every 5 min, auto-discovers projects)")
            else:
                click.echo(f"\nWarning: watchdog plist written but did not bootstrap", err=True)
        return

    project_dir = Path(project).resolve()
    _install_one(project_dir)

    # 4. Watchdog
    if watchdog:
        from superharness.engine.launchd_health import (
            write_watchdog_plist, bootstrap as _bootstrap,
        )
        wp = write_watchdog_plist()
        if _bootstrap(wp):
            click.echo(f"Watchdog installed: {wp.name} (heals every 5 min)")
        else:
            click.echo(f"Warning: watchdog plist written but did not bootstrap", err=True)


@operator.command(name="heal")
@click.option("--project", "-p", default=".", help="Project directory")
@click.option("--auto-discover", is_flag=True, default=False,
              help="Scan for all projects with .superharness/ and heal each one")
@click.option("--quiet", is_flag=True, default=False,
              help="Suppress 'nothing to do' output (for watchdog use)")
def operator_heal(project, auto_discover, quiet):
    """Repair launchd state: bootout zombies, remove stale prior-version
    services and plists, and bootstrap the operator if its plist is on
    disk but not loaded.

    With --auto-discover, scans $HOME/DevOpsSec (or $HOME) for all
    projects containing a .superharness/ directory and heals each one.
    This is the mode the watchdog plist uses to catch every project.
    (Fix: BUGREPORT watcher-silent-death-no-recovery, root cause #4.)
    """
    from pathlib import Path
    import hashlib
    from superharness.engine.launchd_health import heal as _heal, heal_all as _heal_all

    if auto_discover:
        reports = _heal_all()
        total_fixes = sum(r.fixed_count() for r in reports)
        if total_fixes == 0 and quiet:
            return
        for report in reports:
            if report.fixed_count() or not quiet:
                label_str = report.label or "?"
                click.echo(f"[{label_str} | {report.project or '?'}] {report.summary()}")
        if total_fixes:
            click.echo(f"heal-all: fixed {total_fixes} issue(s) across {len(reports)} project(s)")
        return

    project_dir = Path(project).resolve()
    short = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
    operator_label = f"com.superharness.operator.{short}"
    operator_plist = Path.home() / "Library" / "LaunchAgents" / f"{operator_label}.plist"

    report = _heal(operator_plist=operator_plist if operator_plist.is_file() else None)
    if report.fixed_count() == 0 and quiet:
        return
    click.echo(report.summary())


@operator.command(name="stop")
@click.option("--project", "-p", default=".", help="Project directory")
def operator_stop(project):
    """Stop a running operator for this project (uses operator-state.json PID)."""
    import json
    from pathlib import Path
    state_file = Path(project).resolve() / ".superharness" / "operator-state.json"
    if not state_file.exists():
        click.echo("No running operator found (operator-state.json missing).")
        return
    try:
        with open(state_file) as f:
            state = json.load(f)
        pid = int(state.get("operator_pid", 0))
        if pid:
            try:
                import signal as _signal
                os.kill(pid, _signal.SIGTERM)
                click.echo(f"Sent SIGTERM to operator (pid={pid}).")
            except ProcessLookupError:
                click.echo(f"Operator pid={pid} already gone.")
        state_file.unlink(missing_ok=True)
        click.echo("operator-state.json removed.")
    except Exception as e:
        click.echo(f"Error stopping operator: {e}", err=True)


if __name__ == "__main__":
    main()
