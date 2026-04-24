"""shux daemon — portable cross-platform background watcher daemon.

Replaces the platform-specific install scripts (launchd / systemd) with a
single Python-managed daemon that works on macOS, Linux, and Windows.

Usage:
    shux daemon start [--project PATH] [--interval N]
    shux daemon stop  [--project PATH]
    shux daemon status [--project PATH]
    shux daemon restart [--project PATH]
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import click


_DAEMON_STATE_FILE = ".superharness/daemon-state.json"


def _state_file(project_dir: Path) -> Path:
    return project_dir / _DAEMON_STATE_FILE


def _read_state(project_dir: Path) -> dict:
    sf = _state_file(project_dir)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text())
    except Exception:
        return {}


def _write_state(project_dir: Path, state: dict) -> None:
    sf = _state_file(project_dir)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(state, indent=2))


def _is_pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong(STILL_ACTIVE)
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            return exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False  # No such process
    except PermissionError:
        return True   # Process exists; we just lack permission to signal it
    except OSError:
        return False  # Windows: OSError(22) for invalid/out-of-range PID


def _find_watch_script() -> Path | None:
    """Locate the watcher-worker entry point."""
    # Try the installed CLI entry point first
    try:
        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.watcher_worker", "--help"],
            capture_output=True, check=False,
        )
        if result.returncode in (0, 2):
            return None  # Use module invocation
    except Exception:
        pass
    return None


def _start_daemon(project_dir: Path, interval: int) -> None:
    state = _read_state(project_dir)
    pid = state.get("pid")
    if pid and _is_pid_alive(pid):
        click.echo(f"daemon: already running  pid={pid}  project={project_dir}")
        return

    log_dir = project_dir / ".superharness" / "launcher-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    out_log = log_dir / "daemon.out.log"
    err_log = log_dir / "daemon.err.log"

    cmd = [
        sys.executable, "-m", "superharness.commands.inbox_watch",
        "--project", str(project_dir),
        "--interval", str(interval),
        "--loop",
    ]

    out_f = open(str(out_log), "a")
    err_f = open(str(err_log), "a")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=out_f,
            stderr=err_f,
            start_new_session=True,
            cwd=str(project_dir),
        )
    finally:
        out_f.close()
        err_f.close()

    _write_state(project_dir, {
        "pid": proc.pid,
        "project": str(project_dir),
        "interval": interval,
        "log_out": str(out_log),
        "log_err": str(err_log),
    })
    click.echo(f"daemon: started  pid={proc.pid}  interval={interval}s")
    click.echo(f"  logs: {out_log}")
    click.echo(f"  stop: shux daemon stop --project {project_dir}")


def _stop_daemon(project_dir: Path) -> None:
    import signal as _signal

    state = _read_state(project_dir)
    pid = state.get("pid")
    if not pid:
        click.echo("daemon: no state found — not running (or state was lost)")
        return
    if not _is_pid_alive(pid):
        click.echo(f"daemon: process {pid} is not running (cleaning up state)")
        _state_file(project_dir).unlink(missing_ok=True)
        return
    try:
        os.kill(pid, _signal.SIGTERM)
        click.echo(f"daemon: sent SIGTERM to pid={pid}")
    except Exception as exc:
        click.echo(f"daemon: could not stop pid={pid}: {exc}", err=True)
        sys.exit(1)
    _state_file(project_dir).unlink(missing_ok=True)


def _show_status(project_dir: Path) -> None:
    state = _read_state(project_dir)
    if not state:
        click.echo("daemon: not running (no state file)")
        return
    pid = state.get("pid")
    alive = pid and _is_pid_alive(pid)
    status = "running" if alive else "stopped (pid stale)"
    click.echo(f"daemon: {status}")
    click.echo(f"  pid:      {pid}")
    click.echo(f"  project:  {state.get('project', project_dir)}")
    click.echo(f"  interval: {state.get('interval', '?')}s")
    if state.get("log_out"):
        click.echo(f"  out log:  {state['log_out']}")
    if state.get("log_err"):
        click.echo(f"  err log:  {state['log_err']}")
    if not alive:
        click.echo("  tip: shux daemon start")


@click.group(name="daemon")
def cmd_daemon():
    """Manage the background watcher daemon (portable, no launchd/systemd needed)."""


@cmd_daemon.command(name="start")
@click.option("--project", "project_str", default=None, help="Project directory (default: cwd).")
@click.option("--interval", default=30, show_default=True, help="Poll interval in seconds.")
def cmd_daemon_start(project_str, interval):
    """Start the watcher daemon in the background."""
    project_dir = Path(project_str or os.getcwd()).resolve()
    if not (project_dir / ".superharness").exists():
        click.echo(f"error: no .superharness/ found in {project_dir}", err=True)
        click.echo("  run: shux init --project " + str(project_dir), err=True)
        sys.exit(1)
    _start_daemon(project_dir, interval)


@cmd_daemon.command(name="stop")
@click.option("--project", "project_str", default=None, help="Project directory (default: cwd).")
def cmd_daemon_stop(project_str):
    """Stop the running watcher daemon."""
    project_dir = Path(project_str or os.getcwd()).resolve()
    _stop_daemon(project_dir)


@cmd_daemon.command(name="status")
@click.option("--project", "project_str", default=None, help="Project directory (default: cwd).")
def cmd_daemon_status(project_str):
    """Show daemon status (running / stopped)."""
    project_dir = Path(project_str or os.getcwd()).resolve()
    _show_status(project_dir)


@cmd_daemon.command(name="restart")
@click.option("--project", "project_str", default=None, help="Project directory (default: cwd).")
@click.option("--interval", default=30, show_default=True, help="Poll interval in seconds.")
def cmd_daemon_restart(project_str, interval):
    """Restart the watcher daemon."""
    project_dir = Path(project_str or os.getcwd()).resolve()
    _stop_daemon(project_dir)
    _start_daemon(project_dir, interval)
