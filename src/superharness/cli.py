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

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS = str(_importlib_resources.files("superharness").joinpath("scripts"))
_ROOT = os.path.dirname(os.path.dirname(_PACKAGE_DIR))  # repo root (editable installs / shux update)


def _run_script(script: str, args: tuple) -> None:
    """Run a shell script and exit with its return code."""
    path = os.path.join(_SCRIPTS, script)
    result = subprocess.run(["bash", path] + list(args))
    sys.exit(result.returncode)


def _run_module(module: str, args: tuple) -> None:
    """Run a Python command module and exit with its return code."""
    result = subprocess.run([sys.executable, "-m", module] + list(args))
    sys.exit(result.returncode)


@click.group(invoke_without_command=True, context_settings={"help_option_names": ["--help", "-h"]})
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
    # Drop legacy 'today' subcommand token for backward compatibility
    filtered = tuple(a for a in args if a not in ("today", "help"))
    _run_module("superharness.commands.contract_today", filtered)
_cmd("task",            "Create/delete contract tasks.",              module="superharness.commands.task")
_cmd("dispatch",        "Dispatch next inbox item.",                  module="superharness.commands.inbox_dispatch")
_cmd("watch",           "Run one watch cycle or foreground loop.",    module="superharness.commands.inbox_watch")
_cmd("discuss",         "Approval-gated consensus helpers.",         module="superharness.commands.discuss")
_cmd("enqueue",         "Add inbox item.",                           module="superharness.commands.inbox_enqueue")
_cmd("normalize",       "Normalize/archive inbox rows.",             module="superharness.commands.inbox_normalize")
_cmd("recover",         "Recover stale launched items.",             module="superharness.commands.inbox_recover")
_cmd("doctor",          "Check local setup and project health.",     module="superharness.commands.doctor")
_cmd("uninstall",       "Remove system-level artifacts.",            module="superharness.commands.uninstall")
_cmd("status",          "Show watcher and inbox health summary.",    module="superharness.commands.status")
_cmd("notify",          "Send alerts for watcher/retry issues.",     module="superharness.commands.notify")
_cmd("install-wrapper", "Symlink superharness into PATH.",           module="superharness.commands.install_wrapper")
_cmd("recall",          "Search handoffs and ledger by keyword.",    module="superharness.engine.recall")
_cmd("hygiene",         "Check contract hygiene.",                   module="superharness.engine.validate")

# ── Fully ported Python command modules (cross-platform) ─────────────────────

_cmd("init",            "Initialize project protocol files.",        module="superharness.commands.init_project")
_cmd("watcher-worker",  "Build watcher worker and install watcher.", module="superharness.commands.watcher_worker")
_cmd("heartbeat",       "Run proactive watcher checks.",             module="superharness.commands.heartbeat")
_cmd("demo",            "Zero-config task lifecycle walkthrough.",   module="superharness.commands.demo")
_cmd("test-type",       "Set mandatory test types on a task.",       module="superharness.commands.test_type")
_cmd("verify",          "Record verification result for a task.",   module="superharness.commands.verify")
_cmd("close",           "Close a verified task (done + ledger).",   module="superharness.commands.close")


def _run_monitor(args):
    path = os.path.join(_SCRIPTS, "monitor-ui.py")
    args_list = list(args)
    if "--project" not in args_list and "-p" not in args_list:
        args_list = ["--project", os.getcwd()] + args_list
    foreground = "--foreground" in args_list
    if foreground:
        args_list.remove("--foreground")
        result = subprocess.run([sys.executable, path] + args_list)
        sys.exit(result.returncode)
    # Default: background — detach from terminal, return immediately
    import tempfile, time as _time
    url_file = tempfile.mktemp(suffix=".monitor-url")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["SUPERHARNESS_MONITOR_URL_FILE"] = url_file
    proc = subprocess.Popen(
        [sys.executable, "-u", path] + args_list,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    # Wait briefly for the server to write its URL to the temp file
    deadline = _time.monotonic() + 5.0
    while _time.monotonic() < deadline:
        if os.path.exists(url_file):
            with open(url_file) as f:
                for line in f:
                    print(line.rstrip())
            os.unlink(url_file)
            break
        _time.sleep(0.1)
    else:
        print(f"monitor starting in background...")
    print(f"pid: {proc.pid}  (stop with: kill {proc.pid})")


@main.command(name="monitor", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_monitor(args):
    """Launch local watcher dashboard (alias: monitor-ui)."""
    _run_monitor(args)


@main.command(name="monitor-ui", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_monitor_ui(args):
    """Launch local watcher dashboard."""
    _run_monitor(args)


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
        # Look up owner from contract
        contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
        target = None
        if os.path.isfile(contract_file):
            try:
                import yaml
                with open(contract_file) as f:
                    doc = yaml.safe_load(f) or {}
                for t in doc.get("tasks") or []:
                    if isinstance(t, dict) and str(t.get("id", "")) == task_id:
                        owner = str(t.get("owner", ""))
                        if owner in ("claude-code", "codex-cli"):
                            target = owner
                        break
            except Exception as e:
                print(f"Warning: could not read contract for task lookup: {e}", file=sys.stderr)
        if target is None:
            target = "claude-code"
        new_args = ["--to", target, "--task", task_id] + rest
        _run_module("superharness.commands.delegate", tuple(new_args))
    else:
        _run_module("superharness.commands.delegate", args)


@main.command(name="update", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_update(args):
    """Pull latest superharness and refresh project templates."""
    print("superharness — update")
    print("=====================")
    print("Step 1: git pull (updating superharness repo)...")
    r = subprocess.run(["git", "-C", _ROOT, "pull", "--ff-only"])
    if r.returncode != 0:
        sys.exit("git pull failed")
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
  shux monitor             ← open browser dashboard (auto-detects project, opens browser)
  shux test-type <id>      ← set mandatory test types for a task (interactive prompt)
  shux delegate <task-id>  ← create task + enqueue in one step for watcher dispatch
  shux verify <task-id>    ← record verification result (pass/fail) before close
  shux close <task-id>     ← mark task done, append ledger, write handoff (requires verify)
  shux recall <keywords>   ← search past handoffs and ledger entries
  shux hygiene             ← validate protocol compliance (contract, handoffs, ledger)
  shux watch               ← start continuous watcher in foreground
  shux uninstall           ← remove watcher and system artifacts
  shux update              ← git pull + re-run init to refresh templates
  shux discuss <sub>       ← manage discussions and approval gates
  shux help                ← show this message

Full session flow:
  shux init → shux doctor → shux contract → shux continue → shux close <id>""")


@main.command(name="version")
def cmd_version():
    """Show version."""
    click.echo(f"superharness {__version__}")


@main.command(name="help")
@click.pass_context
def cmd_help(ctx):
    """Show help message."""
    click.echo(ctx.parent.get_help())
