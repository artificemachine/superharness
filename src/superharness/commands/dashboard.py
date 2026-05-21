"""Dashboard management — process scanner, health checks, launch/stop/list.

Extracted from cli.py to reduce the entrypoint monolith (C4).
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Optional

import click

logger = logging.getLogger(__name__)


def _find_dashboard_processes() -> list[tuple[int, Optional[int], Optional[str]]]:
    """Return list of (pid, port, project_dir) for all running dashboard-ui.py processes."""
    try:
        ps_out = subprocess.run(
            ["ps", "ax", "-o", "pid=,args="], capture_output=True, text=True
        ).stdout
    except Exception as e:
        logger.warning("Failed to scan dashboard processes: %s", e, exc_info=True)
        return []

    results: list[tuple[int, Optional[int], Optional[str]]] = []
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
        proj: Optional[str] = None
        for i, p in enumerate(parts):
            if p == "--project" and i + 1 < len(parts):
                proj = os.path.realpath(parts[i + 1])
                break

        # Find listening port via lsof
        port: Optional[int] = None
        lsof_out = subprocess.run(
            ["lsof", "-a", "-i", "TCP", "-sTCP:LISTEN", "-n", "-P", "-p", str(pid)],
            capture_output=True, text=True,
        ).stdout
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


def _get_installed_version() -> Optional[str]:
    """Return the installed superharness version, or None if unavailable."""
    try:
        import importlib.metadata as _meta
        return _meta.version("superharness")
    except Exception:
        return None


def _check_dashboard_version(port: int, installed_ver: Optional[str]) -> bool:
    """Return True if the dashboard at `port` matches `installed_ver`."""
    if installed_ver is None:
        return True
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
        with urllib.request.urlopen(req, timeout=2) as resp:
            running_ver = json.loads(resp.read()).get("version", "unknown")
        if running_ver != installed_ver:
            print(f"dashboard version mismatch: running={running_ver} installed={installed_ver} — will restart")
            return False
        return True
    except Exception:
        return False


def _is_dashboard_running(project_dir: Optional[str] = None) -> tuple[bool, Optional[int]]:
    """Return (running: bool, port: int|None) for the dashboard serving project_dir.

    Returns False when the running dashboard's version doesn't match the
    installed version so the caller starts a fresh one.
    If project_dir is None, falls back to checking any dashboard on port 8787.
    """
    installed_ver = _get_installed_version()

    if project_dir is not None:
        real_proj = os.path.realpath(project_dir)

        # Priority 1: operator-state.json
        daemon_file = os.path.join(real_proj, ".superharness", "operator-state.json")
        if os.path.exists(daemon_file):
            try:
                with open(daemon_file) as f:
                    info = json.load(f)
                    port = info.get("dashboard_port")
                    if port:
                        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
                        with urllib.request.urlopen(req, timeout=1) as resp:
                            if resp.status == 200 and _check_dashboard_version(port, installed_ver):
                                return True, port
            except Exception:
                pass

        # Priority 2: process scanning
        for pid, port, proj in _find_dashboard_processes():
            if proj and os.path.realpath(proj) == real_proj and port:
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/status")
                    with urllib.request.urlopen(req, timeout=1) as resp:
                        if resp.status == 200 and _check_dashboard_version(port, installed_ver):
                            return True, port
                except Exception:
                    pass
        return False, None

    # Fallback: check default port 8787
    try:
        req = urllib.request.Request("http://127.0.0.1:8787/api/status")
        with urllib.request.urlopen(req, timeout=1) as resp:
            if resp.status == 200 and _check_dashboard_version(8787, installed_ver):
                return True, 8787
        return False, None
    except Exception:
        return False, None


def _kill_stale_dashboard(proj: str, port: int) -> None:
    """Kill a stale dashboard process for the given project on the given port."""
    for pid, p, dproj in _find_dashboard_processes():
        if dproj and os.path.realpath(dproj) == os.path.realpath(proj) and p == port:
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(1)
            except Exception:
                pass
            break


def _write_operator_state(proj: str, pid: int, port: int, args_list: list[str]) -> None:
    """Write operator-state.json so health checks find the dashboard."""
    try:
        import re as _re
        op_file = os.path.join(proj, ".superharness", "operator-state.json")
        if os.path.isdir(os.path.dirname(op_file)):
            with open(op_file, "w") as f:
                json.dump({
                    "operator_pid": pid,
                    "dashboard_port": port,
                    "started_at": time.time(),
                    "project": proj,
                }, f, indent=2)
    except Exception as e:
        logger.warning("Failed to write operator-state.json: %s", e)


def _launch_dashboard_foreground(script_path: str, args_list: list[str]) -> None:
    """Launch dashboard in foreground and exit with its return code."""
    args_list = [a for a in args_list if a != "--foreground"]
    result = subprocess.run([sys.executable, script_path] + args_list)
    sys.exit(result.returncode)


def _launch_dashboard_background(script_path: str, args_list: list[str]) -> Optional[int]:
    """Launch dashboard in background, wait for URL. Returns PID or None."""
    fd, url_file = tempfile.mkstemp(suffix=".dashboard-url")
    os.close(fd)
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["SUPERHARNESS_DASHBOARD_URL_FILE"] = url_file
    proc = subprocess.Popen(
        [sys.executable, "-u", script_path] + args_list,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )

    deadline = time.monotonic() + 5.0
    url_written = False
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            if os.path.exists(url_file):
                os.unlink(url_file)
            print(f"dashboard failed to start (exit code {proc.returncode})")
            print("tip: run 'superharness dashboard --foreground' to see the error")
            return None
        if os.path.exists(url_file) and os.path.getsize(url_file) > 0:
            with open(url_file) as f:
                for line in f:
                    print(line.rstrip())
            os.unlink(url_file)
            url_written = True
            break
        time.sleep(0.1)

    if not url_written:
        if os.path.exists(url_file):
            os.unlink(url_file)
        print("dashboard starting in background...")

    print(f"pid: {proc.pid}  (stop with: kill {proc.pid})")
    return proc.pid


def run_dashboard(args: tuple, scripts_dir: str) -> None:
    """Launch the dashboard (foreground or background).

    Extracted from cli.py _run_dashboard.
    """
    script_path = os.path.join(scripts_dir, "dashboard-ui.py")
    args_list = list(args)

    if "--help" in args_list or "-h" in args_list:
        result = subprocess.run([sys.executable, script_path] + args_list)
        sys.exit(result.returncode)

    if "--project" not in args_list and "-p" not in args_list:
        args_list = ["--project", os.getcwd()] + args_list

    foreground = "--foreground" in args_list

    # Resolve the project dir being requested
    proj = os.getcwd()
    for i, a in enumerate(args_list):
        if a == "--project" and i + 1 < len(args_list):
            proj = args_list[i + 1]
            break

    if not foreground:
        running, port = _is_dashboard_running(proj)
        if running:
            print(f"dashboard: http://127.0.0.1:{port}  (already running)")
            print(f"project: {proj}")
            return
        _kill_stale_dashboard(proj, port or 8787)

    if foreground:
        _launch_dashboard_foreground(script_path, args_list)
    else:
        pid = _launch_dashboard_background(script_path, args_list)
        if pid:
            # Resolve port from args
            port = 8787
            for i, a in enumerate(args_list):
                if a == "--port" and i + 1 < len(args_list):
                    try:
                        port = int(args_list[i + 1])
                    except ValueError:
                        pass
                    break
            _write_operator_state(proj, pid, port, args_list)


# ── Click commands ──────────────────────────────────────────────────────────

def register_dashboard_commands(main_group: click.Group, scripts_dir: str) -> None:
    """Register all dashboard-related Click commands on the main CLI group."""

    @main_group.command(name="dashboard-kill")
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
        candidates = _find_dashboard_processes()

        if not candidates:
            print("No dashboard processes found.")
            print("  list:   shux dashboard-list")
            print("  start:  shux dashboard")
            return

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
                os.kill(pid, signal.SIGTERM)
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

    @main_group.command(name="dashboard-list")
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

    @main_group.command(name="dashboard", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def cmd_dashboard(args):
        """Launch local browser dashboard (runs setup wizard on first use)."""
        args_list = list(args)

        force_wizard = "--wizard" in args_list
        skip_wizard = "--no-wizard" in args_list
        setup_section = None
        for i, a in enumerate(args_list):
            if a == "--setup" and i + 1 < len(args_list):
                setup_section = args_list[i + 1]
        for flag in ("--wizard", "--no-wizard"):
            while flag in args_list:
                args_list.remove(flag)
        if setup_section:
            for flag in ("--setup", setup_section):
                while flag in args_list:
                    args_list.remove(flag)

        proj = os.getcwd()
        for i, a in enumerate(args_list):
            if a in ("--project", "-p") and i + 1 < len(args_list):
                proj = args_list[i + 1]
                break

        if not skip_wizard and "--help" not in args_list and "-h" not in args_list:
            from superharness.commands.dashboard_wizard import run_wizard, _is_first_time
            should_run = force_wizard or setup_section or _is_first_time(proj)
            if should_run:
                run_wizard(proj, section=setup_section, force=force_wizard)

        run_dashboard(tuple(args_list), scripts_dir)

    @main_group.command(name="dashboard-ui", context_settings={"ignore_unknown_options": True, "allow_extra_args": True, "help_option_names": []})
    @click.argument("args", nargs=-1, type=click.UNPROCESSED)
    def cmd_dashboard_ui(args):
        """Launch local browser dashboard."""
        run_dashboard(args, scripts_dir)
