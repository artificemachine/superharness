"""Python port of inbox-watch.sh.

Watches the inbox and dispatches pending items. Supports single-cycle
(launchd) and foreground (polling) modes.
"""
from __future__ import annotations

import hashlib
import importlib.resources as _importlib_resources
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Lock (directory-based)
# ---------------------------------------------------------------------------

def _lock_key(project_dir: str) -> str:
    return hashlib.sha1(project_dir.encode()).hexdigest()


def _lock_dir_path(project_dir: str) -> str:
    key = _lock_key(project_dir)
    return f"/tmp/superharness-inbox-watch-{key}.lock"


def _auto_break_stale_lock(lock_dir: str, stale_minutes: int) -> bool:
    """Remove lock dir if older than stale_minutes. Returns True if broken."""
    if stale_minutes <= 0:
        return False
    if not os.path.isdir(lock_dir):
        return False
    try:
        stat = os.stat(lock_dir)
        lock_age = time.time() - stat.st_mtime
        stale_secs = stale_minutes * 60
        if lock_age >= stale_secs:
            print(
                f"Auto-breaking stale watcher lock (age: {int(lock_age)}s, "
                f"threshold: {stale_secs}s): {lock_dir}"
            )
            os.rmdir(lock_dir)
            return True
    except OSError:
        pass
    return False


def _acquire_watcher_lock(lock_dir: str) -> bool:
    try:
        os.mkdir(lock_dir)
        return True
    except FileExistsError:
        return False


def _release_watcher_lock(lock_dir: str) -> None:
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Worker sync
# ---------------------------------------------------------------------------

def _sync_worker_copy(project_dir: str) -> None:
    worker_dir = os.path.join(
        os.path.expanduser("~"), ".superharness-workers", os.path.basename(project_dir)
    )
    if not os.path.isdir(worker_dir):
        return
    if not os.path.isdir(os.path.join(project_dir, ".git")):
        return
    try:
        subprocess.run(
            ["rsync", "-a", "--delete",
             "--exclude", ".git",
             "--exclude", ".superharness",
             "--exclude", ".venv",
             "--exclude", "node_modules",
             "--exclude", ".pytest_cache",
             f"{project_dir}/", f"{worker_dir}/"],
            capture_output=True, check=False,
        )
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Single cycle
# ---------------------------------------------------------------------------

def _run_dispatch_cmd(
    project_dir: str,
    target: str,
    print_only: bool,
    non_interactive: bool,
    codex_bypass: bool,
    launcher_timeout: int,
) -> None:
    env = os.environ.copy()

    # Allow test/override via DISPATCH env var (mirrors old inbox-watch.sh behaviour)
    dispatch_override = env.get("DISPATCH", "")
    if dispatch_override and os.path.isfile(dispatch_override):
        args = ["bash", dispatch_override, "--project", project_dir, "--to", target]
        if print_only:
            args.append("--print-only")
        if non_interactive:
            args.append("--non-interactive")
        if codex_bypass:
            args.append("--codex-bypass")
        if launcher_timeout > 0:
            args += ["--launcher-timeout", str(launcher_timeout)]
        # Run in background (detached), like old Bash script used `... &`
        subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return

    args = [sys.executable, "-m", "superharness.commands.inbox_dispatch",
            "--project", project_dir, "--to", target]
    if print_only:
        args.append("--print-only")
    if non_interactive:
        args.append("--non-interactive")
    if codex_bypass:
        args.append("--codex-bypass")
    if launcher_timeout > 0:
        args += ["--launcher-timeout", str(launcher_timeout)]

    subprocess.run(args, check=False, env=env)


def _run_scripts(
    project_dir: str,
    *,
    target: str,
    print_only: bool,
    non_interactive: bool,
    codex_bypass: bool,
    launcher_timeout: int,
    recover_timeout_minutes: int,
    recover_action: str,
) -> None:
    script_dir = _find_scripts_dir()

    # Worker sync
    _sync_worker_copy(project_dir)

    # Deadline check
    deadline_check = os.path.join(script_dir, "inbox-deadline-check.sh")
    if os.path.isfile(deadline_check) and os.access(deadline_check, os.X_OK):
        subprocess.run(["bash", deadline_check, "--project", project_dir],
                       check=False, capture_output=False)

    # Heartbeat: write UTC timestamp so health checks know watcher is alive
    heartbeat_file = os.path.join(project_dir, ".superharness", "watcher.heartbeat")
    try:
        from datetime import datetime, timezone as _tz
        ts = datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(heartbeat_file, "w") as _hf:
            _hf.write(ts + "\n")
    except OSError:
        pass

    # Fire on_watcher_tick hooks (e.g., auto-schedule module)
    try:
        from pathlib import Path
        from superharness.modules.runner import run_hooks
        run_hooks("on_watcher_tick", {"project_dir": project_dir}, Path(project_dir))
    except Exception as e:
        print(f"Warning: on_watcher_tick hook failed: {e}", file=sys.stderr)

    # Reconcile zombie inbox items (launched but process gone)
    try:
        _reconcile_zombies(project_dir)
    except Exception as e:
        print(f"Warning: zombie reconciliation failed: {e}", file=sys.stderr)

    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    if not os.path.exists(inbox_file):
        return

    # Recover stale
    recover = os.path.join(script_dir, "inbox-recover-stale.sh")
    if os.path.isfile(recover) and os.access(recover, os.X_OK):
        subprocess.run(
            ["bash", recover, "--project", project_dir,
             "--timeout-minutes", str(recover_timeout_minutes),
             "--action", recover_action],
            check=False, capture_output=False,
        )

    # Dispatch
    targets = []
    if target == "both":
        targets = ["claude-code", "codex-cli"]
    else:
        targets = [target]

    for t in targets:
        _run_dispatch_cmd(
            project_dir=project_dir,
            target=t,
            print_only=print_only,
            non_interactive=non_interactive,
            codex_bypass=codex_bypass,
            launcher_timeout=launcher_timeout,
        )

    # Discussion dispatch
    disc_dispatch = os.path.join(script_dir, "discussion-dispatch.sh")
    if os.path.isfile(disc_dispatch) and os.access(disc_dispatch, os.X_OK):
        subprocess.run(["bash", disc_dispatch, "--project", project_dir],
                       check=False, capture_output=False)


def _reconcile_zombies(project_dir: str, max_age_seconds: int = 1200) -> int:
    """Reconcile launched inbox items that have no running process.

    Three checks in order:
    1. Contract says done → mark inbox done
    2. PID set but process dead → mark inbox failed
    3. No PID + launched > max_age_seconds ago → mark inbox failed

    Returns count of reconciled items.
    """
    import yaml as _yaml

    harness = os.path.join(project_dir, ".superharness")
    inbox_file = os.path.join(harness, "inbox.yaml")
    contract_file = os.path.join(harness, "contract.yaml")

    if not os.path.exists(inbox_file):
        return 0

    with open(inbox_file, encoding="utf-8") as _f:
        items = _yaml.safe_load(_f.read()) or []
    if not isinstance(items, list):
        return 0

    contract_statuses: dict[str, str] = {}
    if os.path.exists(contract_file):
        with open(contract_file, encoding="utf-8") as _f:
            doc = _yaml.safe_load(_f.read()) or {}
        for t in doc.get("tasks") or []:
            if isinstance(t, dict) and t.get("id"):
                contract_statuses[str(t["id"])] = str(t.get("status", ""))

    now = datetime.now(timezone.utc)
    reconciled = 0
    changed = False

    for item in items:
        if not isinstance(item, dict) or item.get("status") != "launched":
            continue

        task_id = str(item.get("task", ""))
        item_id = str(item.get("id", ""))
        pid = item.get("pid", "")
        launched_at = str(item.get("launched_at", ""))

        # Check 1: contract says done → mark inbox done + kill lingering process
        if contract_statuses.get(task_id) == "done":
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    print(f"zombie-reconcile: killed lingering pid {pid} for {task_id}")
                except (ProcessLookupError, ValueError, PermissionError):
                    pass
            item["status"] = "done"
            item["completed_at"] = _now_utc()
            item["pid"] = ""
            reconciled += 1
            changed = True
            print(f"zombie-reconcile: {item_id} ({task_id}) → done (contract done)")
            continue

        # Check 2: PID set but process dead → mark failed
        if pid:
            try:
                os.kill(int(pid), 0)
                continue  # process alive, skip
            except (ProcessLookupError, ValueError):
                item["status"] = "failed"
                item["failed_at"] = _now_utc()
                item["pid"] = ""
                reconciled += 1
                changed = True
                print(f"zombie-reconcile: {item_id} ({task_id}) → failed (pid {pid} dead)")
                continue
            except PermissionError:
                continue  # process exists but we can't signal it

        # Check 3: no PID + old → mark failed
        if launched_at:
            try:
                lt = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
                age = (now - lt).total_seconds()
                if age > max_age_seconds:
                    item["status"] = "failed"
                    item["failed_at"] = _now_utc()
                    reconciled += 1
                    changed = True
                    print(f"zombie-reconcile: {item_id} ({task_id}) → failed (no pid, {int(age)}s old)")
            except (ValueError, TypeError):
                pass

    if changed:
        with open(inbox_file, "w", encoding="utf-8") as f:
            f.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
            _yaml.dump(items, f, default_flow_style=False, sort_keys=True)

    return reconciled


def _find_scripts_dir() -> str:
    """Locate the scripts/ directory via package data, or env var override."""
    return os.environ.get("SUPERHARNESS_SCRIPTS_DIR") or str(
        _importlib_resources.files("superharness").joinpath("scripts")
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def watch(
    project_dir: str,
    *,
    target: str = "both",
    foreground: bool = False,
    interval: int = 30,
    print_only: bool = False,
    non_interactive: bool = False,
    codex_bypass: bool = False,
    recover_timeout_minutes: int = 20,
    recover_action: str = "stale",
    launcher_timeout: int = 0,
    lock_stale_minutes: int = 30,
    once: bool = False,
) -> int:
    project_dir = os.path.realpath(project_dir)

    if not os.path.isdir(project_dir):
        _abort(f"Project directory does not exist: {project_dir}")

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        _abort(f"Not a superharness project (missing .superharness/): {project_dir}")

    lock_dir = _lock_dir_path(project_dir)

    # Auto-break stale lock
    _auto_break_stale_lock(lock_dir, lock_stale_minutes)

    # Try to acquire lock
    if not _acquire_watcher_lock(lock_dir):
        print(f"Watcher already running for project: {project_dir}")
        return 0

    def _on_exit(signum: int = 0, frame: object = None) -> None:
        _release_watcher_lock(lock_dir)

    import atexit
    atexit.register(_on_exit)

    try:
        dispatch_kwargs = dict(
            target=target,
            print_only=print_only,
            non_interactive=non_interactive,
            codex_bypass=codex_bypass,
            launcher_timeout=launcher_timeout,
            recover_timeout_minutes=recover_timeout_minutes,
            recover_action=recover_action,
        )

        if once or not foreground:
            # Single cycle (launchd / --once)
            _run_scripts(project_dir, **dispatch_kwargs)
        else:
            # Foreground mode
            running = [True]

            def _stop(signum: int, frame: object) -> None:
                running[0] = False
                print("\nWatcher stopped.")
                _release_watcher_lock(lock_dir)
                sys.exit(0)

            signal.signal(signal.SIGINT, _stop)
            signal.signal(signal.SIGTERM, _stop)
            signal.signal(signal.SIGHUP, _stop)

            print(f"superharness watcher (foreground) — project: {project_dir}", flush=True)
            print(f"Polling every {interval}s. Press Ctrl+C to stop.", flush=True)

            while running[0]:
                _run_scripts(project_dir, **dispatch_kwargs)
                end_time = time.time() + interval
                while running[0] and time.time() < end_time:
                    time.sleep(0.1)

    finally:
        _release_watcher_lock(lock_dir)

    return 0


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    class _CapUsage(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(usage, actions, groups, "Usage: ")

    parser = argparse.ArgumentParser(
        prog="inbox_watch",
        description="Watch inbox and dispatch pending items",
        formatter_class=_CapUsage,
        add_help=True,
    )
    parser.add_argument("--project", "-p", required=True)
    parser.add_argument("--to", default="both", dest="target")
    parser.add_argument("--print-only", action="store_true", default=False)
    parser.add_argument("--non-interactive", action="store_true", default=False)
    parser.add_argument("--codex-bypass", action="store_true", default=False)
    parser.add_argument("--recover-timeout-minutes", default="20", dest="recover_timeout_minutes")
    parser.add_argument("--recover-action", default="stale")
    parser.add_argument("--launcher-timeout", default="0")
    parser.add_argument("--lock-stale-minutes", default="30")
    parser.add_argument("--foreground", "-f", action="store_true", default=False)
    parser.add_argument("--interval", "-i", default="30")
    parser.add_argument("--once", action="store_true", default=False,
                        help="Run a single cycle and exit (same as single-cycle / launchd mode)")

    opts = parser.parse_args(argv)

    # Validate integer args
    def _parse_nonneg_int(name: str, val: str) -> int:
        try:
            n = int(val)
            if n < 0:
                raise ValueError
            return n
        except (ValueError, TypeError):
            _abort(f"{name} must be a non-negative integer", 2)

    def _parse_pos_int(name: str, val: str) -> int:
        try:
            n = int(val)
            if n <= 0:
                raise ValueError
            return n
        except (ValueError, TypeError):
            _abort(f"{name} must be a positive integer", 2)

    if opts.target not in ("both", "claude-code", "codex-cli"):
        _abort("--to must be one of: both, claude-code, codex-cli", 2)

    if opts.recover_action not in ("stale", "retry"):
        _abort("--recover-action must be one of: stale, retry", 2)

    recover_timeout_minutes = _parse_nonneg_int("--recover-timeout-minutes", opts.recover_timeout_minutes)
    launcher_timeout = _parse_nonneg_int("--launcher-timeout", opts.launcher_timeout)
    lock_stale_minutes = _parse_nonneg_int("--lock-stale-minutes", opts.lock_stale_minutes)
    interval = _parse_pos_int("--interval", opts.interval)

    rc = watch(
        project_dir=opts.project,
        target=opts.target,
        foreground=opts.foreground,
        interval=interval,
        print_only=opts.print_only,
        non_interactive=opts.non_interactive,
        codex_bypass=opts.codex_bypass,
        recover_timeout_minutes=recover_timeout_minutes,
        recover_action=opts.recover_action,
        launcher_timeout=launcher_timeout,
        lock_stale_minutes=lock_stale_minutes,
        once=opts.once,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
