"""Python port of inbox-dispatch.sh.

Dispatches the next pending inbox item to its target launcher.
"""
from __future__ import annotations

import importlib.resources as _importlib_resources
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

DIRTY_WORKTREE_REASON = "dirty_worktree_requires_user_confirmation"

# Effort → timeout mapping (in seconds)
TIMEOUT_LOW_EFFORT = 900       # 15 minutes
TIMEOUT_MEDIUM_EFFORT = 1800   # 30 minutes
TIMEOUT_HIGH_EFFORT = 3600     # 60 minutes


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _abort(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _safe_task_id_for_path(task_id: str) -> str:
    """Sanitize a task id for use in a single-file path component.

    Task ids such as `discuss-<uuid>/round-N` contain `/` which would make
    `os.path.join(dir, f"{task_id}-...")` resolve into a nonexistent
    subdirectory, silently breaking log writes (script(1) exits 1).

    Mirrors `superharness.commands.discuss.cmd_summary` safe_id handling.
    """
    return task_id.replace("/", "_").replace("..", "_")


# ---------------------------------------------------------------------------
# Lock helpers (mkdir-based, same semantics as shell version)
# ---------------------------------------------------------------------------

class _MkdirLock:
    """Non-blocking mutex using a directory with PID-based orphan detection."""

    def __init__(self, path: str, stale_seconds: int = 300) -> None:
        self.path = path
        self._held = False
        self._stale_seconds = stale_seconds

    def _pid_file(self) -> str:
        return os.path.join(self.path, "owner.pid")

    def _write_pid(self) -> None:
        try:
            with open(self._pid_file(), "w", encoding="utf-8") as f:
                f.write(f"{os.getpid()}\n")
        except OSError:
            pass

    def _read_pid(self) -> int | None:
        try:
            with open(self._pid_file(), encoding="utf-8") as f:
                return int(f.readline().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        if sys.platform == "win32":
            # os.kill(pid, 0) on Windows calls GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid),
            # which sends Ctrl+C to the entire process group — never use it for liveness checks.
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
            return False
        except PermissionError:
            return True
        except OSError:
            return False

    def _break_orphan(self) -> bool:
        """Remove lock if owning PID is dead or lock is stale with no PID."""
        if not os.path.isdir(self.path):
            return False
        pid = self._read_pid()
        if pid is not None and not self._pid_alive(pid):
            print(f"Auto-breaking orphaned dispatch lock (pid {pid} not running): {self.path}")
            self._remove()
            return True
        if pid is None:
            try:
                age = time.time() - os.stat(self.path).st_mtime
            except OSError:
                return False
            if age >= self._stale_seconds:
                print(f"Auto-breaking stale dispatch lock (age: {int(age)}s, no pid): {self.path}")
                self._remove()
                return True
        return False

    def _remove(self) -> None:
        try:
            os.unlink(self._pid_file())
        except OSError:
            pass
        try:
            os.rmdir(self.path)
        except OSError:
            pass

    def acquire(self) -> bool:
        try:
            os.mkdir(self.path)
            self._write_pid()
            self._held = True
            return True
        except FileExistsError:
            if self._break_orphan():
                return self.acquire()
            return False

    def acquire_with_retry(self, attempts: int = 50, delay: float = 0.1) -> bool:
        for _ in range(attempts):
            if self.acquire():
                return True
            time.sleep(delay)
        return False

    def release(self) -> None:
        if self._held:
            self._remove()
            self._held = False


# ---------------------------------------------------------------------------
# Git dirty worktree detection + worktree isolation
# ---------------------------------------------------------------------------


def _git_worktree_add(project_dir: str, task_id: str) -> str | None:
    """Create a temporary git worktree for isolated dispatch. Returns worktree path or None."""
    import tempfile
    import uuid
    worktree_dir = os.path.join(
        tempfile.gettempdir(), "superharness-worktrees",
        f"{task_id}-{uuid.uuid4().hex[:8]}",
    )
    os.makedirs(os.path.dirname(worktree_dir), exist_ok=True)
    r = subprocess.run(
        ["git", "-C", project_dir, "worktree", "add", "--detach", worktree_dir, "HEAD"],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        print(f"git worktree add failed: {r.stderr.strip()}", file=sys.stderr)
        return None
    # Symlink .superharness/ so the agent sees contract, inbox, handoffs
    src_harness = os.path.join(project_dir, ".superharness")
    dst_harness = os.path.join(worktree_dir, ".superharness")
    if os.path.isdir(src_harness) and not os.path.exists(dst_harness):
        os.symlink(src_harness, dst_harness)
    return worktree_dir


def _git_worktree_remove(project_dir: str, worktree_dir: str) -> bool:
    """Remove a temporary git worktree. Returns True on success."""
    # Remove .superharness symlink first (don't let git prune delete the real dir)
    dst_harness = os.path.join(worktree_dir, ".superharness")
    if os.path.islink(dst_harness):
        os.unlink(dst_harness)
    r = subprocess.run(
        ["git", "-C", project_dir, "worktree", "remove", "--force", worktree_dir],
        capture_output=True, text=True, check=False,
    )
    if r.returncode != 0:
        print(f"git worktree remove failed: {r.stderr.strip()}", file=sys.stderr)
        return False
    return True


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


# ---------------------------------------------------------------------------
# Task effort → timeout calculation
# ---------------------------------------------------------------------------

def _get_task_effort_timeout(contract_file: str, task_id: str) -> int:
    """Calculate launcher timeout based on task effort estimate.

    Returns timeout in seconds. Precedence:
    1. estimated_minutes field (if present)
    2. effort field mapped to standard timeouts (low=15min, medium=30min, high=60min)
    3. 0 (no timeout) if neither is set

    Args:
        contract_file: Path to contract.yaml
        task_id: Task ID to look up

    Returns:
        Timeout in seconds, or 0 if no estimate available
    """
    try:
        import yaml
        with open(contract_file) as f:
            doc = yaml.safe_load(f) or {}
    except Exception:
        return 0

    tasks = doc.get("tasks") or []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if str(t.get("id", "")) != task_id:
            continue

        # Priority 1: explicit estimated_minutes
        estimated_minutes = t.get("estimated_minutes")
        if estimated_minutes is not None:
            try:
                return int(estimated_minutes) * 60
            except (ValueError, TypeError):
                pass

        # Priority 2: effort mapping
        effort = t.get("effort")
        if effort == "low":
            return TIMEOUT_LOW_EFFORT
        elif effort == "medium":
            return TIMEOUT_MEDIUM_EFFORT
        elif effort == "high":
            return TIMEOUT_HIGH_EFFORT

        # No estimate found
        return 0

    # Task not found
    return 0


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

def _run_with_timeout(timeout_secs: int, cmd: list[str], inbox_file: str = "", item_id: str = "",
                      env: dict | None = None, stdout=None, stderr=None) -> int:
    """Run a command with a timeout; returns exit code (124 = timed out).

    Uses SIGALRM on POSIX (macOS/Linux). Falls back to a threading.Timer on
    Windows and any platform where SIGALRM is unavailable (Phase 4 reliability).
    """
    _use_sigalrm = hasattr(signal, "SIGALRM")

    # preexec_fn is POSIX-only; skip on Windows
    preexec = os.setsid if hasattr(os, "setsid") else None
    proc = subprocess.Popen(cmd, preexec_fn=preexec, env=env, stdout=stdout, stderr=stderr)
    if inbox_file and item_id:
        _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", str(proc.pid)])

    timed_out = [False]

    if _use_sigalrm:
        def _on_alarm(signum: int, frame: object) -> None:
            timed_out[0] = True
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # type: ignore[attr-defined]
            except (ProcessLookupError, AttributeError):
                pass

        def _on_term(signum: int, frame: object) -> None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)  # type: ignore[attr-defined]
            except (ProcessLookupError, AttributeError):
                pass
            sys.exit(1)

        old_alarm = signal.signal(signal.SIGALRM, _on_alarm)  # type: ignore[attr-defined]
        old_term = signal.signal(signal.SIGTERM, _on_term)
        signal.alarm(timeout_secs)  # type: ignore[attr-defined]
        try:
            rc = proc.wait()
        finally:
            signal.alarm(0)  # type: ignore[attr-defined]
            signal.signal(signal.SIGALRM, old_alarm)  # type: ignore[attr-defined]
            signal.signal(signal.SIGTERM, old_term)
            if inbox_file and item_id:
                _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", ""])
    else:
        # Windows / SIGALRM-unavailable fallback: threading.Timer
        import threading

        def _on_timer() -> None:
            timed_out[0] = True
            try:
                proc.terminate()
            except OSError:
                pass

        timer = threading.Timer(timeout_secs, _on_timer)
        timer.start()
        try:
            rc = proc.wait()
        finally:
            timer.cancel()
            if inbox_file and item_id:
                _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", ""])

    if timed_out[0]:
        return 124
    return rc


# ---------------------------------------------------------------------------
# mark_item_failed / paused
# ---------------------------------------------------------------------------

def _mark_item_failed(inbox_file: str, item_id: str, failed_at: str, lock: _MkdirLock, reason: str = "") -> bool:
    if not lock.acquire_with_retry(50, 0.1):
        print(f"Failed to acquire inbox lock while marking failure for {item_id}", file=sys.stderr)
        return False

    ok = (
        _set_inbox_status(inbox_file, item_id, "launched", "failed", failed_at, "failed_at")
        or _set_inbox_status(inbox_file, item_id, "running", "failed", failed_at, "failed_at")
    )
    if ok and reason:
        _set_inbox_field(inbox_file, item_id, "failed_reason", reason)
    lock.release()
    if ok:
        print(f"Inbox item updated: {item_id} -> failed{' (' + reason + ')' if reason else ''}")
    else:
        print(f"Failed to mark inbox item as failed for {item_id}", file=sys.stderr)
    return ok


def _mark_item_paused_dirty(inbox_file: str, item_id: str, paused_at: str) -> bool:
    if _set_inbox_status(inbox_file, item_id, "pending", "paused", paused_at, "paused_at"):
        _set_inbox_field(inbox_file, item_id, "pause_reason", DIRTY_WORKTREE_REASON)
        print(f"Inbox item updated: {item_id} -> paused (dirty worktree requires interactive confirmation)")
        return True
    return False


def _sqlite_record_review(
    project_dir: str,
    owner: str,
    task_type: str,
    duration_s: float,
    score: float,
    failed: bool,
    now: str,
) -> None:
    """Record dispatch outcome in review_dao for agent performance tracking. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import review_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            review_dao.record(
                conn, owner=owner, task_type=task_type,
                duration_s=duration_s, score=score, failed=failed, now=now,
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _sqlite_mirror_dispatch(
    project_dir: str,
    item_id: str,
    task_id: str,
    agent: str,
    to_status: str,
    now: str,
    *,
    reason: str = "",
) -> None:
    """Mirror inbox dispatch status change to SQLite. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import inbox_dao, ledger_dao, yaml_sync
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            with transaction(conn):
                ledger_dao.record(
                    conn, agent=agent, action=f"dispatch_{to_status}",
                    task_id=task_id, now=now,
                )
                for _from in ("pending", "launched", "running"):
                    if inbox_dao.update_status(
                        conn, item_id,
                        from_status=_from, to_status=to_status,
                        now=now, reason=reason or None,
                    ):
                        break
                yaml_sync.enqueue_op(
                    conn, op_type="update_inbox",
                    payload={"id": item_id, "status": to_status},
                    now=now,
                )
        finally:
            conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Cost extraction helper
# ---------------------------------------------------------------------------

def _read_context_cache_cost(project_dir: str, task_id: str) -> float:
    """Read cost_usd from the context-cache snapshot written by delegate after SDK dispatch."""
    try:
        import yaml
        cache_path = os.path.join(project_dir, ".superharness", "context-cache", f"{task_id}.yaml")
        if not os.path.isfile(cache_path):
            return 0.0
        with open(cache_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return float(data.get("cost_usd", 0.0))
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Main dispatch logic
# ---------------------------------------------------------------------------

def _sqlite_claim_next(project_dir: str, target_agent: str, now: str) -> dict | None:
    """Claim the next pending inbox item via inbox_dao (SQLite-native). Never raises.

    Returns a dict with YAML-shape keys, or None if nothing to claim.
    """
    try:
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            row = inbox_dao.claim_next(conn, target_agent=target_agent, pid=os.getpid(), now=now)
            if row is None:
                return None
            conn.commit()
            d = asdict(row)
            return {
                "id": d["id"],
                "to": d["target_agent"],
                "task": d["task_id"],
                "project": d["project_path"] or "",
                "retry_count": d["retry_count"],
                "max_retries": d["max_retries"],
                "priority": d["priority"],
                "plan_only": d["plan_only"],
            }
        finally:
            conn.close()
    except Exception:
        return None


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

    _backend = os.environ.get("STATE_BACKEND", "").strip().lower()
    _sqlite_primary = _backend == "sqlite_only"
    # Post-migration: SQLite is always the source of truth.
    if not _sqlite_primary:
        try:
            from superharness.engine.sqlite_only import is_sqlite_only
            _sqlite_primary = is_sqlite_only()
        except Exception:
            pass

    if not _sqlite_primary and not os.path.exists(inbox_file):
        print(f"Inbox file not found: {inbox_file}", file=sys.stderr)
        return 1

    # Locate launcher scripts — env var allows tests/CI to inject a different dir
    script_dir = os.environ.get("SUPERHARNESS_SCRIPTS_DIR") or str(
        _importlib_resources.files("superharness").joinpath("scripts")
    )

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
            script_dir=script_dir,
            lock=lock,
            sqlite_primary=_sqlite_primary,
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
    script_dir: str,
    lock: _MkdirLock,
    sqlite_primary: bool = False,
) -> int:
    now_claim = _now_utc()

    if sqlite_primary and target_filter:
        # SQLite-native path: atomically claim next pending item via inbox_dao
        item = _sqlite_claim_next(project_dir, target_filter, now_claim)
        if item is None:
            return 0
        # Log the claim (inbox.yaml transition skipped in sqlite_only)
        print(f"Inbox item claimed from SQLite: {item['id']} → {item['task']} (sqlite_only mode)")
    else:
        # YAML path: read next pending item from inbox.yaml
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

    # Registry-driven launcher selection
    from superharness.engine.adapter_registry import AdapterValidationError, resolve_launcher
    try:
        launcher = resolve_launcher(item_to, script_dir)
    except AdapterValidationError as e:
        print(f"Adapter error for target '{item_to}': {e}", file=sys.stderr)
        return 1

    # Auto-calculate timeout from task effort if not explicitly set
    effective_timeout = launcher_timeout
    if launcher_timeout == 0 and os.path.exists(contract_file):
        effective_timeout = _get_task_effort_timeout(contract_file, item_task)

    # Worktree isolation: if dirty, dispatch in a temporary worktree
    worktree_dir = None
    if non_interactive and not print_only and _has_dirty_worktree(exec_project):
        worktree_dir = _git_worktree_add(exec_project, item_task)
        if worktree_dir:
            print(f"Dispatching in worktree: {worktree_dir} (main worktree is dirty)")
            exec_project = worktree_dir
        else:
            # Worktree creation failed — fall back to pause
            pause_now = _now_utc()
            if _mark_item_paused_dirty(inbox_file, item_id, pause_now):
                return 0

    # Launch transition: in sqlite_only mode, inbox_dao.claim_next() already set status=launched.
    # In YAML mode, explicitly transition via YAML CLI.
    launch_now = _now_utc()
    if sqlite_primary:
        lock.release()
        new_retry_count = item_retry_count
        print(f"Inbox item updated: {item_id} -> launched (priority={item_priority}, retries={new_retry_count}/{item_max_retries})")
    else:
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

        import re
        m = re.search(r"retry_count=(\d+)", lr.stdout)
        new_retry_count = int(m.group(1)) if m else item_retry_count
        print(f"Inbox item updated: {item_id} -> launched (priority={item_priority}, retries={new_retry_count}/{item_max_retries})")
        _sqlite_mirror_dispatch(project_dir, item_id, item_task, item_to, "launched", launch_now)

    # Build launcher args
    launch_args = ["bash", launcher, "--project", exec_project, "--task", item_task]
    task_status = ""
    if os.path.exists(contract_file):
        cr = subprocess.run(
            [sys.executable, "-m", "superharness.engine.contract", "task_status",
             "--file", contract_file, "--task", item_task],
            capture_output=True, text=True, check=False,
        )
        if cr.returncode == 0:
            task_status = cr.stdout.strip()
    if task_status == "review_requested":
        launch_args.append("--for-review")
    if bool(item.get("plan_only", False)):
        launch_args.append("--plan-only")
    elif non_interactive:
        # Implementation tasks in autonomous mode need YOLO permissions
        launch_args.append("--yolo")
    
    if print_only:
        launch_args.append("--print-only")
    if non_interactive:
        launch_args.append("--non-interactive")
    if codex_bypass:
        launch_args.append("--codex-bypass")

    # Per-task log file for live monitoring in launcher-logs/
    launcher_log_dir = os.path.join(project_dir, ".superharness", "launcher-logs")
    os.makedirs(launcher_log_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_item_task = _safe_task_id_for_path(item_task)
    task_log = os.path.join(launcher_log_dir, f"{safe_item_task}-{item_to}-{timestamp}.log")

    # Rotate old logs (keep last 5 per task+agent)
    from pathlib import Path
    from superharness.commands.delegate import _rotate_launcher_logs
    _rotate_launcher_logs(Path(launcher_log_dir), safe_item_task, item_to, keep=5)

    # Pass log path to delegate so SDK runner's JSONL tailer writes to the same file
    spawn_env = os.environ.copy()
    spawn_env["SUPERHARNESS_LAUNCHER_LOG"] = task_log
    # Force Python launcher to flush stdout/stderr immediately — prevents line-dropping
    # when the process is wrapped in a PTY (script command) under load.
    spawn_env["PYTHONUNBUFFERED"] = "1"
    if non_interactive:
        spawn_env["SUPERHARNESS_CONFIRM_NON_INTERACTIVE"] = "YES"

    # Wrap in `script` to capture PTY output (bash launcher needs a terminal).
    # -F (macOS) / -f (Linux): flush output after each write, preventing line-dropping
    # under load when the PTY kernel buffer fills.
    # SUPERHARNESS_NO_PTY_WRAP=1 bypasses this for test/CI environments without a TTY.
    import platform
    if os.environ.get("SUPERHARNESS_NO_PTY_WRAP", "").strip() in ("1", "true", "yes"):
        wrapped_args = launch_args
    elif platform.system() == "Darwin":
        wrapped_args = ["script", "-q", "-F", task_log] + launch_args
    else:
        import shlex
        wrapped_args = ["script", "-q", "-f", "-c", shlex.join(launch_args), task_log]

    # Spawn launcher. --print-only short-circuits here: the caller only wants
    # to see the dispatch decision, not actually invoke the underlying agent
    # CLI (which may not be installed in test/CI environments).
    if print_only:
        launcher_rc = 0
        print(f"[print-only] would launch: {' '.join(launch_args)}")
    else:
        import time as _time
        _launch_start = _time.time()
        if effective_timeout > 0:
            launcher_rc = _run_with_timeout(effective_timeout, wrapped_args, inbox_file=inbox_file, item_id=item_id,
                                            env=spawn_env)
        else:
            proc = subprocess.Popen(wrapped_args, preexec_fn=os.setsid, env=spawn_env)
            _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", str(proc.pid)])
            launcher_rc = proc.wait()
        _inbox_cmd(["set_field", "--file", inbox_file, "--id", item_id, "--key", "pid", "--value", ""])

    # Clean up worktree after agent completes
    if worktree_dir:
        if _git_worktree_remove(project_dir, worktree_dir):
            print(f"Worktree removed: {worktree_dir}")
        else:
            print(f"Warning: worktree cleanup failed for {worktree_dir} — remove manually", file=sys.stderr)

    if launcher_rc != 0:
        fail_now = _now_utc()
        # Exit code 2 == permanent block (lifecycle gate rejected the task). Retrying
        # will fail identically on every attempt, so mark retry_count=max_retries
        # immediately to stop the watcher from burning its retry budget. See
        # superharness.commands.delegate.EXIT_PERMANENT_BLOCK.
        permanent_block = launcher_rc == 2

        # Read log tail for classifier
        log_tail_text = ""
        if os.path.isfile(task_log):
            try:
                from pathlib import Path as _P
                _lines = _P(task_log).read_text(encoding="utf-8", errors="replace").splitlines()
                log_tail_text = "\n".join(_lines[-50:])
            except Exception:
                log_tail_text = ""

        # Classify the failure
        try:
            from superharness.engine.failure_classifier import classify as _classify_failure
            _classification = _classify_failure(
                launcher_rc=launcher_rc, error_text="", log_tail=log_tail_text
            )
            failure_class = _classification.category
            failure_explain = _classification.explain
        except Exception:
            failure_class = "unknown"
            failure_explain = f"launcher exited with code {launcher_rc}"

        if launcher_rc == 124:
            fail_reason = f"launcher timed out after {effective_timeout}s"
            print(f"Launcher timed out after {effective_timeout}s for {item_id}", file=sys.stderr)
        elif permanent_block:
            fail_reason = f"permanent block (lifecycle gate): {failure_explain}"
            print(f"Permanent block for {item_id}: lifecycle gate rejected. Not retrying.", file=sys.stderr)
        else:
            fail_reason = f"{failure_class}: {failure_explain}"
        new_lock = _MkdirLock(inbox_file + ".lock.d")
        _mark_item_failed(inbox_file, item_id, fail_now, new_lock, reason=fail_reason)
        # Stamp structured failure metadata for auto_retry and dashboard surface
        try:
            _inbox_cmd([
                "set_field", "--file", inbox_file, "--id", item_id,
                "--key", "failure_class", "--value", failure_class,
            ])
            _inbox_cmd([
                "set_field", "--file", inbox_file, "--id", item_id,
                "--key", "failure_explain", "--value", failure_explain,
            ])
        except Exception:
            pass
        _sqlite_mirror_dispatch(project_dir, item_id, item_task, item_to, "failed", fail_now, reason=fail_reason)
        if permanent_block or not _classification.retryable:
            # Push retry_count to max_retries so the watcher's next pass sees it as
            # retry-exhausted and does not pick it up again.
            _inbox_cmd([
                "set_field", "--file", inbox_file, "--id", item_id,
                "--key", "retry_count", "--value", str(item_max_retries),
            ])
        try:
            from superharness.commands.notify_desktop import notify_task_event
            notify_task_event(item_task, "failed", item_to)
        except Exception:
            pass

        # Record failure pattern for next dispatch
        try:
            from superharness.engine.failure_patterns import record_failure
            error_snippet = ""
            if os.path.isfile(task_log):
                try:
                    lines = Path(task_log).read_text(encoding="utf-8", errors="replace").splitlines()
                    error_snippet = "\n".join(lines[-50:])
                except Exception:
                    pass
            if launcher_rc == 124:
                error_snippet = f"timed out\n{error_snippet}"
            if error_snippet:
                record_failure(exec_project, item_task, error_snippet, agent=item_to)
        except Exception:
            pass

        # Record benchmark for failed launch
        try:
            from superharness.engine.benchmark import record_dispatch
            outcome = "timeout" if launcher_rc == 124 else "failed"
            record_dispatch(exec_project, item_task, item_to, outcome,
                            _time.time() - _launch_start)
        except Exception:
            pass

        _sqlite_record_review(
            project_dir, owner=item_to, task_type="dispatch",
            duration_s=_time.time() - _launch_start, score=0.0, failed=True, now=fail_now,
        )

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
            if _has_dirty_worktree(exec_project):
                if (_set_inbox_status(inbox_file, item_id, "launched", "paused", reconcile_now, "paused_at")
                        or _set_inbox_status(inbox_file, item_id, "running", "paused", reconcile_now, "paused_at")):
                    _set_inbox_field(inbox_file, item_id, "pause_reason", DIRTY_WORKTREE_REASON)
                    reconciled = 2
            else:
                if (_set_inbox_status(inbox_file, item_id, "launched", "failed", reconcile_now, "failed_at")
                        or _set_inbox_status(inbox_file, item_id, "running", "failed", reconcile_now, "failed_at")):
                    reconciled = 1

        new_lock.release()

        if reconciled > 0:
            _r_status = "paused" if reconciled in (2, 3) else ("done" if final_state == "done" else "failed")
            _sqlite_mirror_dispatch(project_dir, item_id, item_task, item_to, _r_status, reconcile_now)

        if reconciled == 2:
            print(f"Inbox item updated: {item_id} -> paused ({DIRTY_WORKTREE_REASON})")
            return 0
        if reconciled == 3:
            print(f"Inbox item updated: {item_id} -> paused (awaiting_user_approval)")
            try:
                from superharness.commands.notify_desktop import notify_task_event
                notify_task_event(item_task, "waiting_input", item_to)
            except Exception:
                pass
            return 0
        if reconciled == 1:
            _elapsed = _time.time() - _launch_start
            if final_state == "done":
                print(f"Inbox item updated: {item_id} -> done (reconciled from contract task status)")
                try:
                    from superharness.commands.notify_desktop import notify_task_event
                    notify_task_event(item_task, "done", item_to)
                except Exception:
                    pass
                try:
                    from superharness.engine.benchmark import record_dispatch
                    _cost = _read_context_cache_cost(exec_project, item_task)
                    record_dispatch(exec_project, item_task, item_to, "done", _elapsed, cost_usd=_cost)
                except Exception:
                    pass
                _sqlite_record_review(
                    project_dir, owner=item_to, task_type="dispatch",
                    duration_s=_elapsed, score=1.0, failed=False, now=reconcile_now,
                )
                return 0
            print(f"Inbox item updated: {item_id} -> failed (non-interactive launch exited without done/failed)")
            try:
                from superharness.engine.benchmark import record_dispatch
                _cost = _read_context_cache_cost(exec_project, item_task)
                record_dispatch(exec_project, item_task, item_to, "failed", _elapsed, cost_usd=_cost)
            except Exception:
                pass
            _sqlite_record_review(
                project_dir, owner=item_to, task_type="dispatch",
                duration_s=_elapsed, score=0.0, failed=True, now=reconcile_now,
            )
            return 1

    return 0


def _log_dispatch_error(project_dir: str, error: str) -> None:
    """Log a dispatch error to the project's watcher error log. Never raises."""
    try:
        from datetime import datetime, timezone
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log_path = os.path.join(project_dir, ".superharness", "watcher-errors.log")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] dispatch: {error}\n")
    except Exception:
        pass

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

    if opts.target_filter:
        from superharness.engine.adapter_registry import list_adapters
        valid_targets = list_adapters()
        if opts.target_filter not in valid_targets:
            print(f"--to must be one of: {', '.join(valid_targets) or 'none'}", file=sys.stderr)
            sys.exit(2)

    try:
        rc = dispatch(
            project_dir=opts.project,
            target_filter=opts.target_filter or None,
            print_only=opts.print_only,
            non_interactive=opts.non_interactive,
            codex_bypass=opts.codex_bypass,
            launcher_timeout=launcher_timeout,
        )
    except Exception as e:
        _log_dispatch_error(opts.project, f"dispatch raised: {e}")
        raise
    sys.exit(rc)


if __name__ == "__main__":
    main()
