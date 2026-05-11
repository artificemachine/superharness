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
from superharness.logging_utils import get_logger as _bootstrap_logger

# Bootstrap the central logger once so every `logging.getLogger("superharness.*")`
# call in any module propagates to the rotating file handler. Modules don't
# need to know the logger exists — stdlib hierarchy does the routing.
_bootstrap_logger("superharness").debug("cli bootstrap")

# Model shorthand → full model ID used by `shux run --model <shorthand>`.
# "opus" resolves to the current-generation max-tier model.
MODEL_SHORTCUTS: dict[str, str] = {
    "sonnet":    "claude-sonnet-4-6",
    "haiku":     "claude-haiku-4-5-20251001",
    "opus":      "claude-opus-4-7",
    "opus-4-6":  "claude-opus-4-6",
    "opus-4-7":  "claude-opus-4-7",
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
_cmd("task",            "Create/delete contract tasks.",              module="superharness.commands.task")
_cmd("dispatch",        "Dispatch next inbox item.",                  module="superharness.commands.inbox_dispatch")
_cmd("watch",           "Run one watch cycle or foreground loop.",    module="superharness.commands.inbox_watch")
_cmd("discuss",         "Approval-gated consensus helpers.",         module="superharness.commands.discuss")
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
_cmd("rules",           "List, show, or search project rules.",        module="superharness.commands.rules")
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
    except Exception:
        pass

_register_operator_memory()

# explain runs in-process (no subprocess) so CliRunner captures output correctly
def _register_explain():
    try:
        from superharness.commands.explain import cmd_explain
        main.add_command(cmd_explain, name="explain")
        main.add_command(cmd_explain, name="why")
        main.add_command(cmd_explain, name="wtf")
    except Exception:
        pass

_register_explain()

# Daemon is a Click group — import and add directly
def _register_daemon():
    try:
        from superharness.commands.daemon import cmd_daemon
        main.add_command(cmd_daemon)
    except Exception:
        pass

_register_daemon()


# MCP server — Click group
def _register_mcp():
    try:
        from superharness.mcp.cli import cmd_mcp
        main.add_command(cmd_mcp)
    except Exception:
        pass

_register_mcp()


# onboard runs in-process so CliRunner captures output correctly
def _register_onboard():
    try:
        from superharness.commands.onboard import cmd_onboard
        main.add_command(cmd_onboard)
    except Exception:
        pass

_register_onboard()


def _register_config():
    try:
        from superharness.commands.config import cmd_config
        main.add_command(cmd_config)
    except Exception:
        pass

_register_config()


def _register_observation():
    try:
        from superharness.commands.observation import cmd_observation_group
        main.add_command(cmd_observation_group)
    except Exception:
        pass

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
    except Exception:
        pass

_register_workflow()


def _find_dashboard_processes():
    """Return list of (pid, port, project_dir) for all running dashboard-ui.py processes."""
    import subprocess as _sp
    try:
        ps_out = _sp.run(
            ["ps", "ax", "-o", "pid=,args="], capture_output=True, text=True
        ).stdout
    except Exception:
        return []

    results = []
    for line in ps_out.splitlines():
        line = line.strip()
        if not any(pat in line for pat in (
            "dashboard-ui.py", "monitor-ui.py",
            "superharness.scripts.dashboard-ui",
            "superharness.scripts.monitor-ui",
        )):
            continue
        parts = line.split()
        try:
            pid = int(parts[0])
        except (ValueError, IndexError):
            continue

        # Extract --project arg from cmdline
        proj = None
        for i, p in enumerate(parts):
            if p == "--project" and i + 1 < len(parts):
                proj = os.path.realpath(parts[i + 1])
                break

        # Find listening port via lsof
        lsof_out = _sp.run(
            ["lsof", "-a", "-i", "TCP", "-sTCP:LISTEN", "-n", "-P", "-p", str(pid)],
            capture_output=True, text=True,
        ).stdout
        port = None
        for lline in lsof_out.splitlines():
            lparts = lline.split()
            if len(lparts) >= 9:
                addr = lparts[8]
                try:
                    port = int(addr.split(":")[-1])
                except ValueError:
                    pass

        results.append((pid, port, proj))
    return results


def _is_dashboard_running(project_dir: str = None) -> tuple:
    """Return (running: bool, port: int|None) for the dashboard serving project_dir.

    Returns False when the running dashboard's version doesn't match the
    installed version so the caller starts a fresh one.
    If project_dir is None, falls back to checking any dashboard on port 8787.
    """
    import urllib.request
    import json
    try:
        import importlib.metadata as _meta
        _installed_ver = _meta.version("superharness")
    except Exception:
        _installed_ver = None

    def _version_ok(port: int) -> bool:
        """Return True only if the running dashboard version matches installed."""
        if _installed_ver is None:
            return True
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
            with urllib.request.urlopen(req, timeout=2) as resp:
                running_ver = json.loads(resp.read()).get("version", "unknown")
            if running_ver != _installed_ver:
                print(f"dashboard version mismatch: running={running_ver} installed={_installed_ver} — will restart")
                return False
            return True
        except Exception:
            return False

    if project_dir is not None:
        real_proj = os.path.realpath(project_dir)

        # Priority 1: Check operator-state.json for the actual port this project is using
        daemon_file = os.path.join(real_proj, ".superharness", "operator-state.json")
        if os.path.exists(daemon_file):
            try:
                with open(daemon_file, "r") as f:
                    info = json.load(f)
                    port = info.get("dashboard_port")
                    if port:
                        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
                        with urllib.request.urlopen(req, timeout=1) as resp:
                            if resp.status == 200 and _version_ok(port):
                                return True, port
            except Exception:
                pass

        # Priority 2: Fallback to process scanning
        for pid, port, proj in _find_dashboard_processes():
            if proj and os.path.realpath(proj) == real_proj and port:
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        if resp.status == 200 and _version_ok(port):
                            return True, port
                except Exception:
                    pass
        return False, None
    # Fallback: check default port 8787
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/api/status")
        with urllib.request.urlopen(req, timeout=1) as resp:
            if resp.status == 200 and _version_ok(8787):
                return True, 8787
        return False, None
    except Exception:
        return False, None


def _run_dashboard(args):
    path = os.path.join(_SCRIPTS, "dashboard-ui.py")
    args_list = list(args)
    if "--help" in args_list or "-h" in args_list:
        result = subprocess.run([sys.executable, path] + args_list)
        sys.exit(result.returncode)
        return
    if "--project" not in args_list and "-p" not in args_list:
        args_list = ["--project", os.getcwd()] + args_list
    foreground = "--foreground" in args_list

    # Resolve the project dir being requested
    proj = os.getcwd()
    for i, a in enumerate(args_list):
        if a == "--project" and i + 1 < len(args_list):
            proj = args_list[i + 1]
            break

    # Check if a dashboard for THIS project is already running at the correct version
    if not foreground:
        running, port = _is_dashboard_running(proj)
        if running:
            print(f"dashboard: http://127.0.0.1:{port}  (already running)")
            print(f"project: {proj}")
            return
        # Version mismatch: kill any stale process on the target port before starting fresh
        _stale_port = port or 8787
        for _pid, _p, _proj in _find_dashboard_processes():
            if _proj and os.path.realpath(_proj) == os.path.realpath(proj) and _p == _stale_port:
                try:
                    import signal as _sig
                    os.kill(_pid, _sig.SIGTERM)
                    import time as _t
                    _t.sleep(1)
                except Exception:
                    pass
                break

    if foreground:
        args_list.remove("--foreground")
        result = subprocess.run([sys.executable, path] + args_list)
        sys.exit(result.returncode)
    # Default: background — detach from terminal, return immediately
    import tempfile
    import time as _time
    fd, url_file = tempfile.mkstemp(suffix=".dashboard-url")
    os.close(fd)  # Close fd; dashboard-ui.py will write to this path
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["SUPERHARNESS_DASHBOARD_URL_FILE"] = url_file
    proc = subprocess.Popen(
        [sys.executable, "-u", path] + args_list,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    # Wait briefly for the server to write its URL to the temp file
    deadline = _time.monotonic() + 5.0
    url_written = False
    while _time.monotonic() < deadline:
        # Check if process crashed before writing anything
        if proc.poll() is not None:
            if os.path.exists(url_file):
                os.unlink(url_file)
            print(f"dashboard failed to start (exit code {proc.returncode})")
            print("tip: run 'superharness dashboard --foreground' to see the error")
            return
        if os.path.exists(url_file) and os.path.getsize(url_file) > 0:
            with open(url_file) as f:
                for line in f:
                    print(line.rstrip())
            os.unlink(url_file)
            url_written = True
            break
        _time.sleep(0.1)
    if not url_written:
        if os.path.exists(url_file):
            os.unlink(url_file)
        print("dashboard starting in background...")
    print(f"pid: {proc.pid}  (stop with: kill {proc.pid})")

    # Write operator-state.json so _is_dashboard_running() Priority 1 check works
    # reliably on next invocation, even when the operator was never used.
    try:
        import re as _re, json as _json, time as _time2
        port_match = _re.search(r":(\d+)$", url) if url_written else None
        _port = int(port_match.group(1)) if port_match else None
        if not _port:
            for a in args_list:
                if a.isdigit():
                    _port = int(a)
                    break
        if _port:
            _op_file = os.path.join(proj, ".superharness", "operator-state.json")
            if os.path.isdir(os.path.dirname(_op_file)):
                with open(_op_file, "w") as _f:
                    _json.dump({
                        "operator_pid": proc.pid,
                        "dashboard_port": _port,
                        "started_at": _time2.time(),
                        "project": proj,
                    }, _f, indent=2)
    except Exception:
        pass


@main.command(name="dashboard-kill")
@click.option("--port", "-p", type=int, default=None, help="Kill only the dashboard on this port.")
@click.option("--project", "proj", default=None, help="Kill only the dashboard serving this project directory.")
@click.option("--all", "kill_all", is_flag=True, default=False, help="Kill all dashboard processes (default when no filter given).")
def cmd_dashboard_kill(port, proj, kill_all):
    """Kill running dashboard process(es).

    \b
    shux dashboard-kill                        # kill all dashboard processes
    shux dashboard-kill --port 8787            # kill by port
    shux dashboard-kill --project /path/to/p  # kill dashboard for a specific project
    """
    import signal as _signal

    candidates = _find_dashboard_processes()

    if not candidates:
        print("No dashboard processes found.")
        print("  list:   shux dashboard-list")
        print("  start:  shux dashboard")
        return

    # Filter
    targets = candidates
    if port is not None:
        targets = [(pid, p, pj) for pid, p, pj in candidates if p == port]
        if not targets:
            ports_found = [str(p) for _, p, _ in candidates if p]
            print(f"No dashboard found on port {port}. Running on: {', '.join(ports_found) or 'unknown'}")
            sys.exit(1)
    elif proj is not None:
        real_proj = os.path.realpath(proj)
        targets = [(pid, p, pj) for pid, p, pj in candidates if pj and os.path.realpath(pj) == real_proj]
        if not targets:
            print(f"No dashboard found for project: {proj}")
            print("  list running:  shux dashboard-list")
            sys.exit(1)

    killed = 0
    for pid, p, pj in targets:
        port_str = f":{p}" if p else ""
        proj_str = f"  project={pj}" if pj else ""
        try:
            os.kill(pid, _signal.SIGTERM)
            print(f"Killed dashboard  pid={pid}  port{port_str}{proj_str}")
            killed += 1
        except ProcessLookupError:
            print(f"Process {pid} already gone.")
        except PermissionError:
            print(f"Permission denied killing pid {pid}.", file=sys.stderr)

    print(f"{killed} dashboard process(es) stopped.")
    if killed:
        print("  list remaining:  shux dashboard-list")
        print("  restart:         shux dashboard")


@main.command(name="dashboard-list")
def cmd_dashboard_list():
    """List all running dashboard processes with their ports and projects."""
    found = _find_dashboard_processes()

    if not found:
        print("No dashboard processes running.")
        print("  start:  shux dashboard")
        return

    print(f"{'PID':<8} {'PORT':<8} {'PROJECT':<40} URL")
    print("-" * 80)
    for pid, port, proj in found:
        url = f"http://127.0.0.1:{port}" if port else "(port unknown)"
        proj_label = os.path.basename(proj) if proj else "?"
        print(f"{pid:<8} {port or '?':<8} {proj_label:<40} {url}")
    print()
    print("  kill all:              shux dashboard-kill")
    if len(found) == 1:
        pid, port, proj = found[0]
        if port:
            print(f"  kill this one:         shux dashboard-kill --port {port}")
        if proj:
            print(f"  kill by project:       shux dashboard-kill --project {proj}")


@main.command(name="dashboard", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_dashboard(args):
    """Launch local browser dashboard."""
    _run_dashboard(args)


@main.command(name="dashboard-ui", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_dashboard_ui(args):
    """Launch local browser dashboard."""
    _run_dashboard(args)


# Hidden backwards-compat aliases
@main.command(name="monitor", hidden=True, context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_monitor_compat(args):
    """Backwards-compat alias for 'dashboard'."""
    _run_dashboard(args)


@main.command(name="monitor-kill", hidden=True)
@click.option("--port", "-p", type=int, default=None)
@click.option("--project", "proj", default=None)
@click.option("--all", "kill_all", is_flag=True, default=False)
def cmd_monitor_kill_compat(port, proj, kill_all):
    """Backwards-compat alias for 'dashboard-kill'."""
    cmd_dashboard_kill.invoke(click.Context(cmd_dashboard_kill, info_name="dashboard-kill",
                              params={"port": port, "proj": proj, "kill_all": kill_all}))


@main.command(name="monitor-list", hidden=True)
def cmd_monitor_list_compat():
    """Backwards-compat alias for 'dashboard-list'."""
    cmd_dashboard_list.invoke(click.Context(cmd_dashboard_list, info_name="dashboard-list"))


@main.command(name="monitor-ui", hidden=True, context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_monitor_ui_compat(args):
    """Backwards-compat alias for 'dashboard-ui'."""
    _run_dashboard(args)


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


def _is_git_repo(path: str) -> bool:
    r = subprocess.run(["git", "-C", path, "rev-parse", "--git-dir"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


@main.command(name="update", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
def cmd_update(args):
    """Pull latest superharness and refresh project templates."""
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
  shux help                ← show this message

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


@main.command(name="help")
@click.pass_context
def cmd_help(ctx):
    """Show help message."""
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
def operator_start(project, port, no_open):
    """Start the Superharness Guardian (Watcher + Dashboard)."""
    from superharness.engine.operator import Operator
    op = Operator(project)
    op.start_stack(dashboard_port=port, no_open=no_open)
    click.echo(f"dashboard: http://127.0.0.1:{port}")
    click.echo(f"monitor pid: {os.getpid()}")
    click.echo("  (watcher cycles every 15s, dashboard auto-restarts on crash)")
    op.monitor_and_recover()


@operator.command(name="install")
@click.option("--project", "-p", default=".", help="Project directory")
@click.option("--watchdog/--no-watchdog", default=True,
              help="Install a 5-min watchdog plist that re-heals the operator on every tick")
def operator_install(project, watchdog):
    """Install the Guardian as a persistent system service.

    Aggressively removes any stale `com.superharness.*` services and
    orphan plists from prior versions before installing, so old layouts
    can never leak into the new install.
    """
    from pathlib import Path
    import hashlib
    import subprocess

    project_dir = Path(project).resolve()

    # 1. Clean stale services + orphan plists from prior versions BEFORE
    # writing the new plist. This is the fix for "old versions leaking"
    # — any com.superharness.inbox.* / .watcher.* or zombie entries get
    # bootout'd here.
    from superharness.engine.launchd_health import heal as _heal
    pre = _heal(operator_plist=None)
    if pre.fixed_count():
        click.echo(pre.summary())

    # 2. Hand off to the install script which writes + loads the plist.
    script_path = Path(__file__).parent / "scripts" / "install-operator-service.sh"
    if not script_path.exists():
        script_path = Path(sys.prefix) / "lib" / "python3.11" / "site-packages" / "superharness" / "scripts" / "install-operator-service.sh"
    click.echo(f"Installing Superharness service for {project_dir}...")
    subprocess.run(["bash", str(script_path), str(project_dir)], check=True)

    # 3. Self-heal: verify the operator plist actually ended up in launchd.
    # Belt-and-braces in case the install script's `launchctl load` raced
    # or the user previously bootout'd the same label.
    short = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
    operator_label = f"com.superharness.operator.{short}"
    operator_plist = Path.home() / "Library" / "LaunchAgents" / f"{operator_label}.plist"
    post = _heal(operator_plist=operator_plist)
    if post.fixed_count():
        click.echo(post.summary())

    # 4. Watchdog: 5-min ticker that catches the pathological case
    # (operator plist on disk + not loaded → no auto-restart possible).
    if watchdog:
        from superharness.engine.launchd_health import (
            write_watchdog_plist, bootstrap as _bootstrap, watchdog_plist_path,
        )
        wp = write_watchdog_plist()
        if _bootstrap(wp):
            click.echo(f"Watchdog installed: {wp.name} (heals every 5 min)")
        else:
            click.echo(f"Warning: watchdog plist written but did not bootstrap", err=True)


@operator.command(name="heal")
@click.option("--project", "-p", default=".", help="Project directory")
@click.option("--quiet", is_flag=True, default=False,
              help="Suppress 'nothing to do' output (for watchdog use)")
def operator_heal(project, quiet):
    """Repair launchd state: bootout zombies, remove stale prior-version
    services and plists, and bootstrap the operator if its plist is on
    disk but not loaded.
    """
    from pathlib import Path
    import hashlib
    from superharness.engine.launchd_health import heal as _heal

    project_dir = Path(project).resolve()
    short = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
    operator_label = f"com.superharness.operator.{short}"
    operator_plist = Path.home() / "Library" / "LaunchAgents" / f"{operator_label}.plist"

    report = _heal(operator_plist=operator_plist if operator_plist.is_file() else None)
    if report.fixed_count() == 0 and quiet:
        return
    click.echo(report.summary())


if __name__ == "__main__":
    main()
