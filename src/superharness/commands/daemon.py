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
import logging
import os
import subprocess
import sys
from pathlib import Path

import click

logger = logging.getLogger(__name__)

_DAEMON_STATE_FILE = ".superharness/daemon-state.json"


def _state_file(project_dir: Path) -> Path:
    return project_dir / _DAEMON_STATE_FILE


def _find_superharness_python() -> str:
    """Find the Python executable from the superharness pipx venv. Never fails."""
    import shutil
    # Try the dev venv Python first (for development — ensures we use current code)
    dev_venv_python = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".venv", "bin", "python3")
    dev_venv_python = os.path.abspath(dev_venv_python)
    if os.path.isfile(dev_venv_python):
        return dev_venv_python
    # Try the pipx venv Python
    venv_python = os.path.expanduser("~/.local/pipx/venvs/superharness/bin/python3")
    if os.path.isfile(venv_python):
        return venv_python
    # Fallback to whatever python is running right now
    return sys.executable


def _read_state(project_dir: Path) -> dict:
    sf = _state_file(project_dir)
    if not sf.exists():
        return {}
    try:
        return json.loads(sf.read_text())
    except Exception as e:
        logger.warning("daemon.py unexpected error: %s", e, exc_info=True)
        return {}


def _write_state(project_dir: Path, state: dict) -> None:
    sf = _state_file(project_dir)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(state, indent=2))


def _write_monitor_script(project_dir: Path, interval: int,
                          out_log: Path, err_log: Path, watcher_pid: int) -> Path:
    """Write a standalone monitor script that auto-restarts the watcher.

    The caller (`_start_daemon`) already spawned the first watcher and hands
    us its pid as `watcher_pid` — this script must *adopt* that process, not
    spawn a second one. Because the monitor runs as a detached grandchild
    (double-forked, reparented to init/launchd), the adopted watcher is not
    its child, so it cannot `Popen.wait()` on it; it polls liveness instead.
    """
    script = project_dir / ".superharness" / "daemon-monitor.py"
    script.write_text(f'''"""Auto-generated daemon monitor — do not edit."""
import os, sys, time, json, subprocess, signal

import logging
logger = logging.getLogger(__name__)
project_dir = sys.argv[1]
interval = int(sys.argv[2])
out_log = sys.argv[3]
err_log = sys.argv[4]
watcher_pid = int(sys.argv[5])

python = os.path.expanduser("~/.local/pipx/venvs/superharness/bin/python3")
if not os.path.isfile(python):
    python = sys.executable

def spawn():
    cmd = [python, "-m", "superharness.commands.inbox_watch",
           "--project", project_dir, "--interval", str(interval), "--once"]
    env = os.environ.copy()
    src_root = os.path.join(project_dir, "src")
    if os.path.exists(src_root):
        env["PYTHONPATH"] = src_root
    return subprocess.Popen(cmd, stdout=open(out_log, "a"),
                            stderr=open(err_log, "a"),
                            start_new_session=True, cwd=project_dir, env=env)

def write_state(pid):
    sf = os.path.join(project_dir, ".superharness", "daemon-state.json")
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    with open(sf, "w") as f:
        json.dump({{"pid": os.getpid(), "watcher_pid": pid,
                     "project": project_dir, "interval": interval,
                     "log_out": out_log, "log_err": err_log}}, f)

def pid_alive(pid):
    if os.name == "nt":
        # os.kill(pid, 0) on Windows calls GenerateConsoleCtrlEvent(CTRL_C_EVENT,
        # pid) instead of probing the process. The adopted watcher is not in this
        # process's console process group, so that call raises OSError, which a
        # naive except OSError: return False reports as "dead" even though the
        # watcher is alive. Query the handle instead.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong(STILL_ACTIVE)
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True

def wait_for_exit(pid, poll_s=1.0):
    # Not our child (spawned by the parent CLI process before the
    # double-fork), so we cannot Popen.wait() on it — poll liveness instead.
    while pid_alive(pid):
        time.sleep(poll_s)

# Adopt the already-running watcher instead of spawning a second one.
# `proc` stays None until the first respawn — only then are we the real
# parent and can read a real exit code via Popen.wait().
current_pid = watcher_pid
proc = None
write_state(current_pid)

while True:
    if proc is None:
        wait_for_exit(current_pid)
        exit_code = None
    else:
        exit_code = proc.wait()

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_path = os.path.join(project_dir, ".superharness", "watcher-errors.log")
    if exit_code is None:
        msg = f"watcher (pid={{current_pid}}) exited, restarting in 5s"
    elif exit_code == 0:
        msg = "watcher exited cleanly (rc=0), restarting in 5s"
    else:
        msg = f"watcher crashed (rc={{exit_code}}), restarting in 5s"
    try:
        with open(log_path, "a") as lf:
            lf.write(f"[{{ts}}] daemon: {{msg}}\\n")
    except Exception as e:
        logger.warning("daemon.py unexpected error: %s", e, exc_info=True)
        pass
    time.sleep(5)
    proc = spawn()
    current_pid = proc.pid
    write_state(current_pid)
''')
    return script


def _cleanup_monitor_script(script: Path) -> None:
    """Remove the auto-generated monitor script on exit."""
    try:
        script.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("daemon.py unexpected error: %s", e, exc_info=True)
        pass
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
    except Exception as e:
        logger.warning("daemon.py unexpected error: %s", e, exc_info=True)
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

    def _spawn_watcher():
        # Use superharness binary to ensure correct Python env with all dependencies
        python = _find_superharness_python()
        cmd = [
            python, "-m", "superharness.commands.inbox_watch",
            "--project", str(project_dir),
            "--interval", str(interval),
            "--once",
        ]
        env = os.environ.copy()
        if "PYTHONPATH" not in env:
            src_root = project_dir / "src"
            if src_root.exists():
                env["PYTHONPATH"] = str(src_root)
        return subprocess.Popen(
            cmd,
            stdout=open(str(out_log), "a"),
            stderr=open(str(err_log), "a"),
            start_new_session=True,
            cwd=str(project_dir),
            env=env,
        )

    from superharness.logging_utils import get_logger, get_audit_logger
    log = get_logger("daemon")
    audit = get_audit_logger()

    proc = _spawn_watcher()

    _write_state(project_dir, {
        "pid": proc.pid,
        "project": str(project_dir),
        "interval": interval,
        "log_out": str(out_log),
        "log_err": str(err_log),
    })
    log.info("daemon started: pid=%d interval=%ds project=%s", proc.pid, interval, project_dir)
    audit.info("daemon spawn: pid=%d project=%s", proc.pid, project_dir)
    click.echo(f"daemon: started  pid={proc.pid}  interval={interval}s")
    click.echo(f"  logs: {out_log}")
    click.echo(f"  stop: shux daemon stop --project {project_dir}")

    # Auto-upgrade check: restart daemon if a newer pipx version is installed
    _check_version_and_upgrade(project_dir)

    # Detach monitor as a subprocess so it survives CLI exit.
    # Previously a daemon thread — died with the launcher, leaving no
    # auto-restart and a stale PID in daemon-state.json.
    # Use double-fork: first fork creates a child, second fork creates a grandchild
    # that is reparented to PID 1 (launchd on macOS, init on Linux).
    # Monitor script is written to .superharness/ (gitignored, harmless to leave).
    _monitor_script = _write_monitor_script(project_dir, interval, out_log, err_log, proc.pid)
    _monitor_env = os.environ.copy()
    if "PYTHONPATH" not in _monitor_env:
        src_root = project_dir / "src"
        if src_root.exists():
            _monitor_env["PYTHONPATH"] = str(src_root)

    # Monitor script writes its own PID to state file on start

    _monitor_argv = [
        _find_superharness_python(), str(_monitor_script),
        str(project_dir), str(interval),
        str(out_log), str(err_log), str(proc.pid),
    ]
    if hasattr(os, "fork"):
        # POSIX: double-fork so the grandchild reparents to init/launchd
        # and survives CLI exit.
        # First fork
        _monitor_pid = os.fork()
        if _monitor_pid == 0:
            # Child: second fork to create grandchild (reparented to init)
            if os.fork() > 0:
                os._exit(0)  # First child exits immediately
            # Grandchild: the actual monitor
            os.setsid()
            os.chdir(str(project_dir))
            os.umask(0)
            # Close inherited fds, open devnull for standard streams
            os.closerange(0, 3)
            os.open(os.devnull, os.O_RDONLY)  # stdin
            os.open(os.devnull, os.O_WRONLY)  # stdout
            os.open(os.devnull, os.O_WRONLY)  # stderr
            # Execute monitor script
            os.execvpe(_monitor_argv[0], _monitor_argv, _monitor_env)
        # Parent: wait for first child to exit
        os.waitpid(_monitor_pid, 0)
    else:
        # Windows: os.fork/os.setsid do not exist. Without this branch
        # `shux daemon start` raised AttributeError after printing "started"
        # and the monitor/auto-restart process was never created. Spawn the
        # monitor as a detached background process instead.
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        subprocess.Popen(
            _monitor_argv,
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            cwd=str(project_dir),
            env=_monitor_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    # Monitor script writes its own PID to state file on start


# Confirmed-death poll after signalling, used by _stop_daemon. Module-level
# so tests can shrink them instead of sleeping for real.
_STOP_POLL_TIMEOUT_S = 5.0
_STOP_POLL_INTERVAL_S = 0.2


def _stop_daemon(project_dir: Path) -> None:
    import signal as _signal
    import time as _time

    state = _read_state(project_dir)
    pid = state.get("pid")
    watcher_pid = state.get("watcher_pid")
    if not pid:
        click.echo("daemon: no state found — not running (or state was lost)")
        return

    monitor_alive = _is_pid_alive(pid)
    watcher_alive = bool(watcher_pid) and _is_pid_alive(watcher_pid)
    if not monitor_alive and not watcher_alive:
        click.echo(f"daemon: process {pid} is not running (cleaning up state)")
        _state_file(project_dir).unlink(missing_ok=True)
        return

    if monitor_alive:
        try:
            if hasattr(os, "killpg"):
                try:
                    pgid = os.getpgid(pid)
                    os.killpg(pgid, _signal.SIGTERM)
                    click.echo(f"daemon: sent SIGTERM to process group {pgid}")
                except OSError:
                    # Fallback to single PID if PGID lookup fails
                    os.kill(pid, _signal.SIGTERM)
                    click.echo(f"daemon: sent SIGTERM to pid={pid} (pgid lookup failed)")
            else:
                os.kill(pid, _signal.SIGTERM)
                click.echo(f"daemon: sent SIGTERM to pid={pid}")
        except Exception as exc:
            click.echo(f"daemon: could not stop pid={pid}: {exc}", err=True)

    # The watcher is spawned with start_new_session=True, so it lives in its
    # own process group and the killpg above never reaches it — signal it
    # directly or it survives as a permanent orphan holding the lock.
    if watcher_alive:
        try:
            os.kill(watcher_pid, _signal.SIGTERM)
            click.echo(f"daemon: sent SIGTERM to watcher pid={watcher_pid}")
        except Exception as exc:
            click.echo(f"daemon: could not stop watcher pid={watcher_pid}: {exc}", err=True)

    # Don't remove the state file — and let `status` report "not running" —
    # until both pids are actually gone, or an orphan can hold the lock
    # while the CLI already believes the daemon is stopped.
    deadline = _time.time() + _STOP_POLL_TIMEOUT_S
    while _time.time() < deadline:
        if not _is_pid_alive(pid) and not (watcher_pid and _is_pid_alive(watcher_pid)):
            break
        _time.sleep(_STOP_POLL_INTERVAL_S)

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


def _check_version_and_upgrade(project_dir):
    """Check if a newer pipx version is installed and auto-restart if so."""
    try:
        import importlib.metadata, subprocess
        current = importlib.metadata.version('superharness')
        # Check if we should track version
        state_file = os.path.join(str(project_dir), '.superharness', 'daemon-state.json')
        import json
        if os.path.isfile(state_file):
            state = json.load(open(state_file))
            last_version = state.get('version', '')
            if last_version and last_version != current:
                import sys
                print(f'daemon: version upgraded {last_version} -> {current}, restarting...')
                os.execv(sys.executable, [sys.executable] + sys.argv)
            state['version'] = current
            json.dump(state, open(state_file, 'w'))
    except Exception as e:
        logger.warning("daemon.py unexpected error: %s", e, exc_info=True)
        pass