"""Python port of inbox-dispatch.sh.

Dispatches the next pending inbox item to its target launcher.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone

DIRTY_WORKTREE_REASON = "dirty_worktree_requires_user_confirmation"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


# ---------------------------------------------------------------------------
# Lock helpers (mkdir-based, same semantics as shell version)
# ---------------------------------------------------------------------------

class _MkdirLock:
    """Non-blocking mutex using a directory (same as shell inbox-dispatch.sh)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._held = False

    def acquire(self) -> bool:
        try:
            os.mkdir(self.path)
            self._held = True
            return True
        except FileExistsError:
            return False

    def acquire_with_retry(self, attempts: int = 50, delay: float = 0.1) -> bool:
        import time
        for _ in range(attempts):
            if self.acquire():
                return True
            time.sleep(delay)
        return False

    def release(self) -> None:
        if self._held:
            try:
                os.rmdir(self.path)
            except OSError:
                pass
            self._held = False


# ---------------------------------------------------------------------------
# Git dirty worktree detection
# ---------------------------------------------------------------------------

def _has_dirty_worktree(project_dir: str) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", project_dir, "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, check=False,
        )
        if r.returncode != 0:
            return False
        r2 = subprocess.run(
            ["git", "-C", project_dir, "status", "--porcelain",
             "--untracked-files=normal", "--", ":!.superharness/"],
            capture_output=True, text=True, check=False,
        )
        return bool(r2.stdout.strip())
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Inbox engine helpers
# ---------------------------------------------------------------------------

def _inbox_cmd(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "superharness.engine.inbox"] + args,
        capture_output=True, text=True, check=False,
    )


def _contract_cmd(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "superharness.engine.contract"] + args,
        capture_output=True, text=True, check=False,
    )


def _set_inbox_field(inbox_file: str, item_id: str, key: str, value: str) -> None:
    _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", key, "--value", value])


def _set_inbox_status(inbox_file: str, item_id: str, from_: str, to: str, now: str, stamp_key: str) -> bool:
    r = _inbox_cmd([
        "set_status", "--file", inbox_file, "--id", item_id,
        "--from", from_, "--to", to, "--now", now, "--stamp-key", stamp_key,
    ])
    return r.returncode == 0


# ---------------------------------------------------------------------------
# Timeout subprocess runner
# ---------------------------------------------------------------------------

def _run_with_timeout(timeout_secs: int, cmd: list[str]) -> int:
    """Run a command with a timeout; returns exit code (124 = timed out)."""
    proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
    timed_out = [False]

    def _on_alarm(signum: int, frame: object) -> None:
        timed_out[0] = True
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    old_handler = signal.signal(signal.SIGALRM, _on_alarm)
    signal.alarm(timeout_secs)
    try:
        rc = proc.wait()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    if timed_out[0]:
        return 124
    return rc


# ---------------------------------------------------------------------------
# mark_item_failed / paused
# ---------------------------------------------------------------------------

def _mark_item_failed(inbox_file: str, item_id: str, failed_at: str, lock: _MkdirLock) -> bool:
    if not lock.acquire_with_retry(50, 0.1):
        print(f"Failed to acquire inbox lock while marking failure for {item_id}", file=sys.stderr)
        return False

    ok = (
        _set_inbox_status(inbox_file, item_id, "launched", "failed", failed_at, "failed_at")
        or _set_inbox_status(inbox_file, item_id, "running", "failed", failed_at, "failed_at")
    )
    lock.release()
    if ok:
        print(f"Inbox item updated: {item_id} -> failed")
    else:
        print(f"Failed to mark inbox item as failed for {item_id}", file=sys.stderr)
    return ok


def _mark_item_paused_dirty(inbox_file: str, item_id: str, paused_at: str) -> bool:
    if _set_inbox_status(inbox_file, item_id, "pending", "paused", paused_at, "paused_at"):
        _set_inbox_field(inbox_file, item_id, "pause_reason", DIRTY_WORKTREE_REASON)
        print(f"Inbox item updated: {item_id} -> paused (dirty worktree requires interactive confirmation)")
        return True
    return False


# ---------------------------------------------------------------------------
# Main dispatch logic
# ---------------------------------------------------------------------------

def dispatch(
    project_dir: str,
    target_filter: str | None = None,
    print_only: bool = False,
    non_interactive: bool = False,
    codex_bypass: bool = False,
    launcher_timeout: int = 0,
) -> int:
    project_dir = os.path.realpath(project_dir)
    harness_dir = os.path.join(project_dir, ".superharness")
    inbox_file = os.path.join(harness_dir, "inbox.yaml")
    contract_file = os.path.join(harness_dir, "contract.yaml")

    if not os.path.exists(inbox_file):
        print(f"Inbox file not found: {inbox_file}", file=sys.stderr)
        return 1

    # Locate launcher scripts
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))))), "scripts")
    # Fall back to searching from known location
    if not os.path.isdir(script_dir):
        script_dir = os.path.join(os.path.dirname(sys.executable), "..", "..", "scripts")
    if not os.path.isdir(script_dir):
        script_dir = os.path.join(os.getcwd(), "scripts")

    launch_claude = os.path.join(script_dir, "delegate-to-claude.sh")
    launch_codex = os.path.join(script_dir, "delegate-to-codex.sh")

    # Lock
    lock = _MkdirLock(inbox_file + ".lock.d")
    if not lock.acquire():
        print(f"Another inbox dispatcher is active for {inbox_file}; skipping.")
        return 0

    try:
        return _do_dispatch(
            inbox_file=inbox_file,
            contract_file=contract_file,
            project_dir=project_dir,
            target_filter=target_filter,
            print_only=print_only,
            non_interactive=non_interactive,
            codex_bypass=codex_bypass,
            launcher_timeout=launcher_timeout,
            launch_claude=launch_claude,
            launch_codex=launch_codex,
            lock=lock,
        )
    finally:
        lock.release()


def _do_dispatch(
    inbox_file: str,
    contract_file: str,
    project_dir: str,
    target_filter: str | None,
    print_only: bool,
    non_interactive: bool,
    codex_bypass: bool,
    launcher_timeout: int,
    launch_claude: str,
    launch_codex: str,
    lock: _MkdirLock,
) -> int:
    # Read next pending item
    next_args = ["next_pending", "--file", inbox_file]
    if target_filter:
        next_args += ["--to", target_filter]

    r = _inbox_cmd(next_args[1:] if next_args[0] == "next_pending" else next_args)
    # Re-run correctly
    r = subprocess.run(
        [sys.executable, "-m", "superharness.engine.inbox", "next_pending",
         "--file", inbox_file] + (["--to", target_filter] if target_filter else []),
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        print(f"Failed to read pending inbox item from {inbox_file}: {r.stderr.strip()}", file=sys.stderr)
        return 1

    item_json = r.stdout.strip()
    if not item_json:
        return 0

    try:
        item = json.loads(item_json)
    except json.JSONDecodeError as e:
        print(f"Failed to parse pending inbox item from {inbox_file}: {e}", file=sys.stderr)
        return 1

    item_id = str(item.get("id", ""))
    item_to = str(item.get("to", ""))
    item_task = str(item.get("task", ""))
    item_project = str(item.get("project", "") or project_dir)
    item_retry_count = int(item.get("retry_count", 0))
    item_max_retries = int(item.get("max_retries", 3))
    item_priority = int(item.get("priority", 2))

    if not item_project:
        item_project = project_dir

    # Determine execution project (worker mode)
    exec_project = item_project
    try:
        proj_harness_real = os.path.realpath(os.path.join(project_dir, ".superharness"))
        item_harness_real = os.path.realpath(os.path.join(item_project, ".superharness"))
        if (
            proj_harness_real == item_harness_real
            and project_dir != item_project
            and os.path.isdir(proj_harness_real)
        ):
            exec_project = project_dir
    except OSError:
        pass

    # Launcher selection
    if item_to == "claude-code":
        launcher = launch_claude
    elif item_to == "codex-cli":
        launcher = launch_codex
    else:
        print(f"Unsupported target '{item_to}' for inbox item '{item_id}'", file=sys.stderr)
        return 1

    # Dirty worktree pre-check
    if non_interactive and not print_only and item_to == "codex-cli" and _has_dirty_worktree(exec_project):
        pause_now = _now_utc()
        if _mark_item_paused_dirty(inbox_file, item_id, pause_now):
            return 0

    # Launch transition
    launch_now = _now_utc()
    lr = subprocess.run(
        [sys.executable, "-m", "superharness.engine.inbox", "launch",
         "--file", inbox_file, "--id", item_id, "--now", launch_now],
        capture_output=True, text=True, check=False,
    )
    launch_rc = lr.returncode

    lock.release()  # Release before spawning launcher

    if launch_rc == 4:
        print(f"Inbox item updated: {item_id} -> failed (retry limit reached: {item_retry_count}/{item_max_retries})")
        return 1

    if launch_rc != 0:
        print(f"Failed to launch inbox item transition for {item_id}: {lr.stdout.strip()}", file=sys.stderr)
        return 1

    # Parse new retry count from output
    import re
    m = re.search(r"retry_count=(\d+)", lr.stdout)
    new_retry_count = int(m.group(1)) if m else item_retry_count
    print(f"Inbox item updated: {item_id} -> launched (priority={item_priority}, retries={new_retry_count}/{item_max_retries})")

    # Build launcher args
    launch_args = ["bash", launcher, "--project", exec_project, "--task", item_task]
    if print_only:
        launch_args.append("--print-only")
    if non_interactive:
        launch_args.append("--non-interactive")
    if codex_bypass:
        launch_args.append("--codex-bypass")

    # Spawn launcher
    if launcher_timeout > 0:
        launcher_rc = _run_with_timeout(launcher_timeout, launch_args)
    else:
        proc = subprocess.Popen(launch_args, preexec_fn=os.setsid)
        _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", str(proc.pid)])
        launcher_rc = proc.wait()
        _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", ""])

    if launcher_rc != 0:
        fail_now = _now_utc()
        if launcher_rc == 124:
            print(f"Launcher timed out after {launcher_timeout}s for {item_id}", file=sys.stderr)
        new_lock = _MkdirLock(inbox_file + ".lock.d")
        _mark_item_failed(inbox_file, item_id, fail_now, new_lock)
        return 1

    # Reconcile in non-interactive mode
    if non_interactive and not print_only:
        reconcile_now = _now_utc()
        new_lock = _MkdirLock(inbox_file + ".lock.d")
        if not new_lock.acquire_with_retry(50, 0.1):
            print(f"Failed to acquire inbox lock while reconciling status for {item_id}", file=sys.stderr)
            return 1

        final_state = ""
        if os.path.exists(contract_file):
            cr = subprocess.run(
                [sys.executable, "-m", "superharness.engine.contract", "task_status",
                 "--file", contract_file, "--task", item_task],
                capture_output=True, text=True, check=False,
            )
            if cr.returncode == 0:
                final_state = cr.stdout.strip()

        reconciled = 0

        if final_state == "done":
            if (_set_inbox_status(inbox_file, item_id, "launched", "done", reconcile_now, "done_at")
                    or _set_inbox_status(inbox_file, item_id, "running", "done", reconcile_now, "done_at")):
                reconciled = 1
        elif final_state == "failed":
            if (_set_inbox_status(inbox_file, item_id, "launched", "failed", reconcile_now, "failed_at")
                    or _set_inbox_status(inbox_file, item_id, "running", "failed", reconcile_now, "failed_at")):
                reconciled = 1
        elif final_state == "pending_user_approval":
            if (_set_inbox_status(inbox_file, item_id, "launched", "paused", reconcile_now, "paused_at")
                    or _set_inbox_status(inbox_file, item_id, "running", "paused", reconcile_now, "paused_at")):
                _set_inbox_field(inbox_file, item_id, "pause_reason", "awaiting_user_approval")
                reconciled = 3
        else:
            if item_to == "codex-cli" and _has_dirty_worktree(exec_project):
                if (_set_inbox_status(inbox_file, item_id, "launched", "paused", reconcile_now, "paused_at")
                        or _set_inbox_status(inbox_file, item_id, "running", "paused", reconcile_now, "paused_at")):
                    _set_inbox_field(inbox_file, item_id, "pause_reason", DIRTY_WORKTREE_REASON)
                    reconciled = 2
            else:
                if (_set_inbox_status(inbox_file, item_id, "launched", "failed", reconcile_now, "failed_at")
                        or _set_inbox_status(inbox_file, item_id, "running", "failed", reconcile_now, "failed_at")):
                    reconciled = 1

        new_lock.release()

        if reconciled == 2:
            print(f"Inbox item updated: {item_id} -> paused ({DIRTY_WORKTREE_REASON})")
            return 0
        if reconciled == 3:
            print(f"Inbox item updated: {item_id} -> paused (awaiting_user_approval)")
            return 0
        if reconciled == 1:
            if final_state == "done":
                print(f"Inbox item updated: {item_id} -> done (reconciled from contract task status)")
                return 0
            print(f"Inbox item updated: {item_id} -> failed (non-interactive launch exited without done/failed)")
            return 1

    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    class _CapUsage(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(usage, actions, groups, "Usage: ")

    parser = argparse.ArgumentParser(
        prog="inbox_dispatch",
        description="Dispatch next pending inbox item to target launcher",
        formatter_class=_CapUsage,
        add_help=True,
    )
    parser.add_argument("--project", "-p", required=True)
    parser.add_argument("--to", default=None, dest="target_filter")
    parser.add_argument("--print-only", action="store_true", default=False)
    parser.add_argument("--non-interactive", action="store_true", default=False)
    parser.add_argument("--codex-bypass", action="store_true", default=False)
    parser.add_argument("--launcher-timeout", default="0")

    opts = parser.parse_args(argv)

    # Validate launcher-timeout as non-negative integer
    try:
        launcher_timeout = int(opts.launcher_timeout)
        if launcher_timeout < 0:
            raise ValueError
    except (ValueError, TypeError):
        print("--launcher-timeout must be a non-negative integer", file=sys.stderr)
        sys.exit(2)

    if opts.target_filter and opts.target_filter not in ("claude-code", "codex-cli"):
        print("--to must be claude-code or codex-cli", file=sys.stderr)
        sys.exit(2)

    rc = dispatch(
        project_dir=opts.project,
        target_filter=opts.target_filter or None,
        print_only=opts.print_only,
        non_interactive=opts.non_interactive,
        codex_bypass=opts.codex_bypass,
        launcher_timeout=launcher_timeout,
    )
    sys.exit(rc)


if __name__ == "__main__":
    main()
