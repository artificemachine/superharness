"""shux daemon's watcher-supervisor loop — a real, importable, coverable module.

Iteration 3 of PLAN-coding-practices.md: this used to be a ~90-line Python
program that `daemon.py`'s `_write_monitor_script` wrote out as a string to
`.superharness/daemon-monitor.py` in the target project and launched as a
bare script. That string was never importable, never covered, and every
existing test on it had to assert on its *text* rather than its behaviour.
It is now launched as `python -m superharness.commands.daemon_monitor`.

Role: `_start_daemon` spawns the first watcher itself and hands this module
its pid as `watcher_pid`. This module *adopts* that process rather than
spawning a second one. Because the monitor runs as a detached grandchild
(double-forked on POSIX, reparented to init/launchd; a detached process on
Windows), the adopted watcher is not its child, so it cannot `Popen.wait()`
on it — it polls liveness via `engine.process.pid_alive` instead. Once the
adopted watcher exits (or the monitor itself respawns one after a crash),
the new process *is* the monitor's child and `Popen.wait()` is used from
then on.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time

from superharness.engine.process import pid_alive

logger = logging.getLogger(__name__)


def _find_python() -> str:
    python = os.path.expanduser("~/.local/pipx/venvs/superharness/bin/python3")
    if not os.path.isfile(python):
        python = sys.executable
    return python


def _spawn_watcher(project_dir: str, interval: int, out_log: str, err_log: str) -> subprocess.Popen:
    cmd = [_find_python(), "-m", "superharness.commands.inbox_watch",
           "--project", project_dir, "--interval", str(interval), "--once"]
    env = os.environ.copy()
    src_root = os.path.join(project_dir, "src")
    if os.path.exists(src_root):
        env["PYTHONPATH"] = src_root
    return subprocess.Popen(
        cmd,
        stdout=open(out_log, "a"),
        stderr=open(err_log, "a"),
        start_new_session=True,
        cwd=project_dir,
        env=env,
    )


def _write_state(project_dir: str, interval: int, out_log: str, err_log: str, watcher_pid: int) -> None:
    """Key set must stay exactly {pid, watcher_pid, project, interval,
    log_out, log_err} — daemon._read_state, daemon._show_status, and
    `shux status` all consume this file."""
    sf = os.path.join(project_dir, ".superharness", "daemon-state.json")
    os.makedirs(os.path.dirname(sf), exist_ok=True)
    with open(sf, "w") as f:
        json.dump({
            "pid": os.getpid(),
            "watcher_pid": watcher_pid,
            "project": project_dir,
            "interval": interval,
            "log_out": out_log,
            "log_err": err_log,
        }, f)


def _restart_message(exit_code: int | None) -> str:
    if exit_code is None:
        return "watcher exited, restarting in 5s"
    if exit_code == 0:
        return "watcher exited cleanly (rc=0), restarting in 5s"
    return f"watcher crashed (rc={exit_code}), restarting in 5s"


def _log_restart(project_dir: str, message: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    log_path = os.path.join(project_dir, ".superharness", "watcher-errors.log")
    try:
        with open(log_path, "a") as lf:
            lf.write(f"[{ts}] daemon: {message}\n")
    except OSError as e:
        logger.warning("daemon_monitor unexpected error: %s", e, exc_info=True)


def run_monitor(
    project_dir: str,
    interval: int,
    out_log: str,
    err_log: str,
    watcher_pid: int,
    *,
    spawn=None,
    sleep=time.sleep,
    alive=pid_alive,
) -> None:
    """Adopt → wait → respawn, forever. `spawn`/`sleep`/`alive` are
    injectable so this loop is testable without any real process.
    """
    if spawn is None:
        def spawn():
            return _spawn_watcher(project_dir, interval, out_log, err_log)

    current_pid = watcher_pid
    proc = None
    _write_state(project_dir, interval, out_log, err_log, current_pid)

    while True:
        if proc is None:
            # Not our child — spawned by the parent CLI process before the
            # double-fork — so we cannot Popen.wait() on it; poll instead.
            while alive(current_pid):
                sleep(1.0)
            exit_code = None
        else:
            exit_code = proc.wait()

        _log_restart(project_dir, _restart_message(exit_code))
        sleep(5)
        proc = spawn()
        current_pid = proc.pid
        _write_state(project_dir, interval, out_log, err_log, current_pid)


def main(argv: list[str]) -> None:
    if len(argv) < 5 or argv[0] in ("-h", "--help"):
        print(
            "usage: python -m superharness.commands.daemon_monitor "
            "PROJECT_DIR INTERVAL OUT_LOG ERR_LOG WATCHER_PID",
            file=sys.stderr,
        )
        sys.exit(2)
    project_dir = argv[0]
    interval = int(argv[1])
    out_log = argv[2]
    err_log = argv[3]
    watcher_pid = int(argv[4])
    run_monitor(project_dir, interval, out_log, err_log, watcher_pid)


if __name__ == "__main__":
    main(sys.argv[1:])
