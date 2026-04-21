"""Python port of inbox-watch.sh.

Watches the inbox and dispatches pending items. Supports single-cycle
(launchd) and foreground (polling) modes.
"""
from __future__ import annotations

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

def _lock_dir_path(project_dir: str) -> str:
    from superharness.engine.platform_runtime import watcher_lock_path
    return watcher_lock_path(project_dir)


def _lock_pid_file(lock_dir: str) -> str:
    return os.path.join(lock_dir, "owner.pid")


def _write_lock_pid(lock_dir: str) -> None:
    try:
        with open(_lock_pid_file(lock_dir), "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()}\n")
    except OSError:
        pass


def _read_lock_pid(lock_dir: str) -> int | None:
    try:
        with open(_lock_pid_file(lock_dir), encoding="utf-8") as f:
            raw = f.readline().strip()
        pid = int(raw)
        return pid if pid > 0 else None
    except (OSError, ValueError):
        return None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
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
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _heartbeat_age_seconds(project_dir: str) -> int | None:
    hb_file = os.path.join(project_dir, ".superharness", "watcher.heartbeat")
    if not os.path.isfile(hb_file):
        return None
    try:
        with open(hb_file, encoding="utf-8") as f:
            hb_ts = f.readline().strip()
        if not hb_ts:
            return None
        hb_dt = datetime.fromisoformat(hb_ts.replace("Z", "+00:00"))
        return int((datetime.now(timezone.utc) - hb_dt).total_seconds())
    except (OSError, ValueError):
        return None


def _remove_lock_dir(lock_dir: str) -> None:
    try:
        os.unlink(_lock_pid_file(lock_dir))
    except OSError:
        pass
    try:
        os.rmdir(lock_dir)
    except OSError:
        pass


def _auto_break_stale_lock(
    lock_dir: str,
    stale_minutes: int,
    *,
    project_dir: str | None = None,
    heartbeat_stale_seconds: int | None = None,
) -> bool:
    """Remove an orphaned or stale lock dir. Returns True if broken."""
    if not os.path.isdir(lock_dir):
        return False

    lock_pid = _read_lock_pid(lock_dir)
    if lock_pid is not None and not _pid_is_running(lock_pid):
        print(f"Auto-breaking orphaned watcher lock (pid {lock_pid} not running): {lock_dir}")
        _remove_lock_dir(lock_dir)
        return True

    try:
        stat = os.stat(lock_dir)
        lock_age = time.time() - stat.st_mtime
        if (
            project_dir
            and heartbeat_stale_seconds is not None
            and lock_pid is None
        ):
            hb_age = _heartbeat_age_seconds(project_dir)
            if hb_age is not None and hb_age >= heartbeat_stale_seconds and lock_age >= heartbeat_stale_seconds:
                print(
                    f"Auto-breaking orphaned watcher lock "
                    f"(stale heartbeat: {hb_age}s, no lock pid): {lock_dir}"
                )
                _remove_lock_dir(lock_dir)
                return True

        if stale_minutes <= 0:
            return False

        stale_secs = stale_minutes * 60
        if lock_pid is None and lock_age >= stale_secs:
            print(
                f"Auto-breaking stale watcher lock (age: {int(lock_age)}s, "
                f"threshold: {stale_secs}s): {lock_dir}"
            )
            _remove_lock_dir(lock_dir)
            return True
    except OSError:
        pass
    return False


def _acquire_watcher_lock(lock_dir: str) -> bool:
    try:
        os.mkdir(lock_dir)
        _write_lock_pid(lock_dir)
        return True
    except FileExistsError:
        return False


def _release_watcher_lock(lock_dir: str) -> None:
    _remove_lock_dir(lock_dir)


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
    from superharness.engine.platform_runtime import sync_worker_copy
    sync_worker_copy(project_dir, worker_dir)


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


def _run_scripts_heartbeat(project_dir: str) -> None:
    """Write both legacy timestamp and structured heartbeat contract for the watcher."""
    # Legacy: plain timestamp — consumed by existing health checks
    heartbeat_file = os.path.join(project_dir, ".superharness", "watcher.heartbeat")
    try:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(heartbeat_file, "w") as _hf:
            _hf.write(ts + "\n")
    except OSError:
        pass

    # Heartbeat contract v1: YAML heartbeat — runtime-agnostic, consumed by dashboard
    try:
        from superharness.engine.heartbeat_contract import AgentHeartbeat, write_heartbeat
        write_heartbeat(project_dir, AgentHeartbeat(
            agent_id="watcher", runtime="native", status="idle", pid=os.getpid(),
        ))
    except Exception:
        pass


def auto_enqueue_todo(project_dir: str) -> int:
    """Scan contract.yaml for todo tasks and enqueue them for planning.

    Only runs when auto_dispatch=True and autonomy=autonomous in profile.yaml.
    Enqueues with --plan-only logic in mind (handled by dispatcher).
    """
    import uuid
    from datetime import datetime, timezone

    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.exists(profile_file):
        return 0
    try:
        import yaml as _yaml
        profile = _yaml.safe_load(open(profile_file, encoding="utf-8").read()) or {}
    except Exception:
        return 0
    
    # Must be auto_dispatch AND autonomous to start new plans automatically
    if not profile.get("auto_dispatch") or profile.get("autonomy") != "autonomous":
        return 0

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")

    if not os.path.exists(contract_file):
        return 0

    try:
        import yaml as _yaml
        contract = _yaml.safe_load(open(contract_file, encoding="utf-8").read()) or {}
        tasks = contract.get("tasks") or []
    except Exception:
        return 0

    inbox_items: list[dict] = []
    if os.path.exists(inbox_file):
        try:
            import yaml as _yaml
            inbox_items = _yaml.safe_load(open(inbox_file, encoding="utf-8").read()) or []
        except Exception:
            inbox_items = []

    _ACTIVE = {"pending", "launched", "running", "paused"}
    active_inbox_items = [
        item for item in inbox_items
        if isinstance(item, dict) and str(item.get("status", "")) in _ACTIVE
    ]
    active_tasks = {str(item.get("task", "")) for item in active_inbox_items}

    # Safety throttle: respect max_concurrent_tasks from profile
    max_concurrent = int(profile.get("max_concurrent_tasks", 2))
    if len(active_inbox_items) >= max_concurrent:
        return 0

    try:
        from superharness.engine.inbox import _deps_satisfied
    except ImportError:
        _deps_satisfied = None  # type: ignore[assignment]

    added = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for task in tasks:
        if not isinstance(task, dict):
            continue
        # Only target 'todo' tasks for auto-planning
        if task.get("status") != "todo":
            continue
        
        task_id = str(task.get("id", ""))
        if not task_id:
            continue
        if task_id in active_tasks:
            continue
            
        # Respect dependencies
        if _deps_satisfied is not None:
            if not _deps_satisfied(contract_file, task_id):
                continue

        owner = str(task.get("owner", "claude-code"))
        item_id = f"auto-plan-{uuid.uuid4().hex[:6]}"
        new_item: dict = {
            "id": item_id,
            "task": task_id,
            "to": owner,
            "status": "pending",
            "priority": 2,
            "retry_count": 0,
            "max_retries": 3,
            "created_at": now,
            "project": project_dir,
            "plan_only": True, # Hint for the dispatcher
        }
        inbox_items.append(new_item)
        active_tasks.add(task_id)
        added += 1
        print(f"auto-dispatch: enqueued todo {task_id} for planning → {owner} (item {item_id})")

    if added > 0:
        import yaml as _yaml
        try:
            from superharness.engine.inbox import _inbox_lock
            with _inbox_lock(inbox_file):
                with open(inbox_file, "w", encoding="utf-8") as _f:
                    _f.write("# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n")
                    _yaml.dump(inbox_items, _f, default_flow_style=False, sort_keys=True)
        except Exception as e:
            print(f"auto-dispatch: failed to write inbox: {e}", file=sys.stderr)
            return 0

    return added


def auto_enqueue_approved(project_dir: str) -> int:
    """Scan contract.yaml for plan_approved tasks and enqueue them to inbox.yaml.

    Only runs when auto_dispatch=True in profile.yaml. Skips tasks that already
    have an active inbox entry (pending/launched/running/paused). Uses
    _deps_satisfied to respect blocked_by dependencies.

    Returns the number of tasks newly enqueued.
    """
    import uuid
    from datetime import datetime, timezone

    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if not os.path.exists(profile_file):
        return 0
    try:
        import yaml as _yaml
        profile = _yaml.safe_load(open(profile_file, encoding="utf-8").read()) or {}
    except Exception:
        return 0
    if not profile.get("auto_dispatch"):
        return 0
    
    # Must be autonomous or oversight to auto-enqueue implementation work
    autonomy = profile.get("autonomy", "ai_driven")
    if autonomy not in ("autonomous", "oversight", "ai_driven"):
        return 0

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")

    if not os.path.exists(contract_file):
        return 0

    try:
        import yaml as _yaml
        contract = _yaml.safe_load(open(contract_file, encoding="utf-8").read()) or {}
        tasks = contract.get("tasks") or []
    except Exception:
        return 0

    inbox_items: list[dict] = []
    if os.path.exists(inbox_file):
        try:
            import yaml as _yaml
            inbox_items = _yaml.safe_load(open(inbox_file, encoding="utf-8").read()) or []
        except Exception:
            inbox_items = []

    _ACTIVE = {"pending", "launched", "running", "paused"}
    active_inbox_items = [
        item for item in inbox_items
        if isinstance(item, dict) and str(item.get("status", "")) in _ACTIVE
    ]
    active_tasks = {str(item.get("task", "")) for item in active_inbox_items}

    # Safety throttle: respect max_concurrent_tasks from profile
    max_concurrent = int(profile.get("max_concurrent_tasks", 2))
    if len(active_inbox_items) >= max_concurrent:
        return 0

    try:
        from superharness.engine.inbox import _deps_satisfied
    except ImportError:
        _deps_satisfied = None  # type: ignore[assignment]

    added = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("status") != "plan_approved":
            continue
        task_id = str(task.get("id", ""))
        if not task_id:
            continue
        if task_id in active_tasks:
            continue
        if _deps_satisfied is not None:
            if not _deps_satisfied(contract_file, task_id):
                continue

        owner = str(task.get("owner", "claude-code"))
        item_id = f"auto-{uuid.uuid4().hex[:6]}"
        new_item: dict = {
            "id": item_id,
            "task": task_id,
            "to": owner,
            "status": "pending",
            "priority": 2,
            "retry_count": 0,
            "max_retries": 3,
            "created_at": now,
            "project": project_dir,
        }
        inbox_items.append(new_item)
        active_tasks.add(task_id)
        added += 1
        print(f"auto-dispatch: enqueued {task_id} → {owner} (item {item_id})")

    if added > 0:
        import yaml as _yaml
        try:
            with open(inbox_file, "w", encoding="utf-8") as _f:
                _f.write(_yaml.dump(inbox_items, default_flow_style=False))
        except Exception as e:
            print(f"auto-dispatch: failed to write inbox: {e}", file=sys.stderr)
            return 0

    return added


_PR_URL_RE = __import__("re").compile(r"https://github\.com/[^/]+/[^/]+/pull/\d+")


def _find_pr_url_in_handoff(handoff_dir: str, task_id: str) -> str | None:
    """Return the first GitHub PR URL found in any handoff outcome for task_id."""
    import glob as _glob
    import yaml as _yaml

    pattern = os.path.join(handoff_dir, f"*{task_id}*")
    for path in sorted(_glob.glob(pattern)):
        try:
            doc = _yaml.safe_load(open(path, encoding="utf-8").read()) or {}
            for item in doc.get("outcomes") or []:
                m = _PR_URL_RE.search(str(item))
                if m:
                    return m.group(0)
        except Exception:
            continue
    return None


def _check_ship_on_complete_tasks(project_dir: str) -> None:
    """For ship_on_complete tasks at report_ready with no PR URL, mark failed."""
    import yaml as _yaml

    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.isfile(contract_file):
        return
    try:
        contract = _yaml.safe_load(open(contract_file, encoding="utf-8").read()) or {}
    except Exception:
        return

    changed = False
    tasks = contract.get("tasks") or []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        if not task.get("ship_on_complete"):
            continue
        if task.get("status") != "report_ready":
            continue
        task_id = str(task.get("id", ""))
        if not task_id:
            continue
        handoff_dir = os.path.join(project_dir, ".superharness", "handoffs")
        pr_url = _find_pr_url_in_handoff(handoff_dir, task_id)
        if not pr_url:
            task["status"] = "failed"
            changed = True
            print(
                f"ship_on_complete: task '{task_id}' reached report_ready without a PR URL "
                f"in handoff outcomes — marking failed.",
                file=sys.stderr,
            )

    if changed:
        try:
            with open(contract_file, "w", encoding="utf-8") as _f:
                _f.write(_yaml.dump(contract, default_flow_style=False))
        except Exception as e:
            print(f"ship_on_complete: failed to write contract: {e}", file=sys.stderr)


def run_once(
    project_dir: str,
    *,
    to: str = "both",
    non_interactive: bool = False,
    recover_timeout_minutes: int = 3,
    recover_action: str = "retry",
    launcher_timeout: int = 0,
) -> None:
    """Run a single watcher tick without acquiring the watcher lock. For tests."""
    _run_scripts(
        project_dir,
        target=to,
        print_only=False,
        non_interactive=non_interactive,
        codex_bypass=False,
        launcher_timeout=launcher_timeout,
        recover_timeout_minutes=recover_timeout_minutes,
        recover_action=recover_action,
    )


# Mutable cycle counter for GC interval tracking (reset per watcher session)
_watcher_cycle_count = [0]

DEFAULT_GC_INTERVAL_CYCLES = 5


def _run_gc_if_due(project_dir: str, cycle_count: int) -> bool:
    """Run inbox GC if the current cycle is a multiple of gc_interval_cycles. Returns True if GC ran."""
    gc_interval = DEFAULT_GC_INTERVAL_CYCLES
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if os.path.isfile(profile_file):
        try:
            import yaml as _yaml
            with open(profile_file) as f:
                profile = _yaml.safe_load(f) or {}
            gc_interval = int(profile.get("gc_interval_cycles", DEFAULT_GC_INTERVAL_CYCLES))
        except Exception:
            pass
    if gc_interval < 1:
        gc_interval = DEFAULT_GC_INTERVAL_CYCLES
    if cycle_count % gc_interval != 0:
        return False
    from superharness.commands.inbox_gc import run_gc
    result = run_gc(project_dir)
    return result.get("reconciled", 0) >= 0


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

    # Heartbeat: write legacy timestamp + structured contract heartbeat
    _run_scripts_heartbeat(project_dir)

    # Fire on_watcher_tick hooks (e.g., auto-schedule module)
    try:
        from pathlib import Path
        from superharness.modules.runner import run_hooks
        run_hooks("on_watcher_tick", {"project_dir": project_dir}, Path(project_dir))
    except Exception as e:
        print(f"Warning: on_watcher_tick hook failed: {e}", file=sys.stderr)

    # ship_on_complete guard: mark failed when report_ready has no PR URL
    try:
        _check_ship_on_complete_tasks(project_dir)
    except Exception as e:
        print(f"Warning: _check_ship_on_complete_tasks failed: {e}", file=sys.stderr)

    # Auto-enqueue todo tasks for planning when auto_dispatch=True and autonomy=autonomous
    try:
        auto_enqueue_todo(project_dir)
    except Exception as e:
        print(f"Warning: auto_enqueue_todo failed: {e}", file=sys.stderr)

    # Auto-enqueue plan_approved tasks when auto_dispatch=True in profile.yaml
    try:
        auto_enqueue_approved(project_dir)
    except Exception as e:
        print(f"Warning: auto_enqueue_approved failed: {e}", file=sys.stderr)

    # Reconcile zombie inbox items (launched but process gone)
    try:
        _reconcile_zombies(project_dir)
    except Exception as e:
        print(f"Warning: zombie reconciliation failed: {e}", file=sys.stderr)

    # Inbox GC: reconcile stale items against contract
    try:
        _watcher_cycle_count[0] += 1
        _run_gc_if_due(project_dir, _watcher_cycle_count[0])
    except Exception as e:
        print(f"Warning: inbox gc failed: {e}", file=sys.stderr)

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
                pid_int = int(pid)
            except ValueError:
                pid_int = None
            if not _pid_is_running(pid_int):
                item["status"] = "failed"
                item["failed_at"] = _now_utc()
                item["pid"] = ""
                reconciled += 1
                changed = True
                print(f"zombie-reconcile: {item_id} ({task_id}) → failed (pid {pid} dead)")
            continue

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
        from superharness.engine.inbox import _inbox_lock
        with _inbox_lock(inbox_file):
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
    _auto_break_stale_lock(
        lock_dir,
        lock_stale_minutes,
        project_dir=project_dir,
        heartbeat_stale_seconds=max(interval * 2, 60),
    )

    # Try to acquire lock
    if not _acquire_watcher_lock(lock_dir):
        print(f"Watcher already running for project: {project_dir}")
        return 0

    def _on_exit(signum: int = 0, frame: object = None) -> None:
        _release_watcher_lock(lock_dir)
        if signum:
            sys.exit(0)

    import atexit
    atexit.register(_on_exit)
    signal.signal(signal.SIGTERM, _on_exit)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _on_exit)

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
            if hasattr(signal, "SIGHUP"):
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
