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



def _load_tasks(project_dir: str) -> list[dict]:
    """Return all contract tasks via state_reader (SQLite)."""
    try:
        from superharness.engine.state_reader import get_tasks
        return get_tasks(project_dir)
    except Exception:
        return []


def _deps_satisfied_from_tasks(tasks: list[dict], task_id: str) -> bool:
    """Dependency check using an already-loaded task list (no file I/O)."""
    task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
    if task is None:
        return True
    blocked_by = task.get("blocked_by")
    if not blocked_by or str(blocked_by).strip().lower() in ("none", "", "null"):
        return True
    if isinstance(blocked_by, str):
        dep_ids = [d.strip() for d in blocked_by.split(",") if d.strip()]
    elif isinstance(blocked_by, list):
        dep_ids = [str(d).strip() for d in blocked_by if str(d).strip()]
    else:
        return True
    status_map = {str(t.get("id", "")): str(t.get("status", "")) for t in tasks if isinstance(t, dict)}
    return all(status_map.get(dep_id, "") == "done" for dep_id in dep_ids)


def _ensure_task_in_sqlite(conn, task_id: str, project_dir: str, now: str) -> None:
    """Upsert a minimal task row if it is not yet in SQLite. Never raises."""
    try:
        from superharness.engine import tasks_dao
        if tasks_dao.get(conn, task_id) is not None:
            return
        import yaml as _yaml
        contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
        if not os.path.exists(contract_file):
            return
        with open(contract_file, encoding="utf-8") as _f:
            doc = _yaml.safe_load(_f) or {}
        td = next(
            (t for t in (doc.get("tasks") or []) if isinstance(t, dict) and t.get("id") == task_id),
            None,
        )
        if td is None:
            return
        row = tasks_dao.TaskRow(
            id=task_id,
            title=str(td.get("title", task_id)),
            owner=td.get("owner"),
            status=str(td.get("status", "todo")),
            effort=td.get("effort"),
            project_path=td.get("project_path"),
            development_method=td.get("development_method"),
            acceptance_criteria=td.get("acceptance_criteria") or [],
            test_types=td.get("test_types") or [],
            out_of_scope=td.get("out_of_scope") or [],
            definition_of_done=td.get("definition_of_done") or [],
            context=td.get("context"),
            tdd=td.get("tdd"),
            version=1,
            created_at=td.get("created_at") or now,
            blocked_by=td.get("blocked_by") or [],
        )
        tasks_dao.upsert(conn, row)
    except Exception:
        pass


def _sqlite_mirror_inbox_enqueue(project_dir: str, items: list[dict], now: str) -> None:
    """Mirror new inbox items to SQLite. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import inbox_dao, ledger_dao, yaml_sync
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            with transaction(conn):
                for item in items:
                    task_id = str(item.get("task", item.get("task_id", "")))
                    _ensure_task_in_sqlite(conn, task_id, project_dir, now)
                    inbox_dao.enqueue(
                        conn,
                        id=str(item["id"]),
                        task_id=task_id,
                        target_agent=str(item.get("to", item.get("target_agent", ""))),
                        priority=int(item.get("priority", 2)),
                        max_retries=int(item.get("max_retries", 3)),
                        project_path=item.get("project", item.get("project_path")),
                        plan_only=bool(item.get("plan_only", False)),
                        now=item.get("created_at", now),
                    )
                    yaml_sync.enqueue_op(
                        conn,
                        op_type="enqueue_inbox",
                        payload=item,
                        now=now,
                    )
                ledger_dao.record(
                    conn, agent="watcher", action="auto_enqueue",
                    details={"count": len(items)}, now=now,
                )
        finally:
            conn.close()
    except Exception:
        pass


def _sqlite_mirror_inbox_retry(project_dir: str, retried_items: list[dict], now: str) -> None:
    """Mirror inbox retry resets to SQLite. Never raises.

    Each entry in retried_items must have 'id' and 'retry_count'.
    """
    try:
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import inbox_dao, ledger_dao, yaml_sync
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            with transaction(conn):
                for item in retried_items:
                    item_id = str(item["id"])
                    retry_count = int(item.get("retry_count", 0))
                    inbox_dao.set_retry(conn, item_id, retry_count, None, now)
                    yaml_sync.enqueue_op(
                        conn,
                        op_type="update_inbox",
                        payload={"id": item_id, "status": "pending"},
                        now=now,
                    )
                ledger_dao.record(
                    conn, agent="watcher", action="auto_retry",
                    details={"ids": [i["id"] for i in retried_items]}, now=now,
                )
        finally:
            conn.close()
    except Exception:
        pass


def _sqlite_mirror_task_status(
    project_dir: str, task_id: str, status: str, now: str, extra: dict | None = None
) -> None:
    """Mirror a task status change to SQLite. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import tasks_dao, ledger_dao, yaml_sync
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            with transaction(conn):
                task = tasks_dao.get(conn, task_id)
                if task is None:
                    return
                changes: dict = {"status": status, **(extra or {})}
                payload: dict = {"id": task_id, **changes}
                tasks_dao.update(conn, task_id, task.version, changes=changes)
                yaml_sync.enqueue_op(
                    conn,
                    op_type="update_task_status",
                    payload=payload,
                    now=now,
                )
                ledger_dao.record(
                    conn, agent="watcher", action="task_status_change",
                    task_id=task_id, details={"status": status}, now=now,
                )
        finally:
            conn.close()
    except Exception:
        pass

def _log_watcher_error(project_dir, component, error):
    """Write watcher errors to a log file."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log_path = os.path.join(project_dir, ".superharness", "watcher-errors.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"[{ts}] [{component}] {error}\n")


def _abort(msg: str, code: int = 1) -> None:
    from superharness.logging_utils import get_logger
    get_logger("inbox_watch").error("abort: %s", msg)
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


def _reconcile_paused_dead_pids(inbox: list) -> bool:
    """Transition paused items whose launcher pid is dead to failed.

    Returns True if any item was changed.
    Called on every watcher tick so dead-pid lanes are unblocked within one interval.
    Only acts on items with status=paused AND a recorded pid.
    Items without a pid are left alone, handled by lifecycle_rules.reconcile_lifecycle instead.
    """
    changed = False
    for item in inbox:
        if item.get("status") != "paused":
            continue
        raw_pid = item.get("pid")
        if not raw_pid:
            continue
        try:
            pid = int(raw_pid)
        except (ValueError, TypeError):
            continue
        if not _pid_is_running(pid):
            item["status"] = "failed"
            item["failed_reason"] = f"launcher pid {pid} disappeared"
            item["failed_at"] = _now_utc()
            changed = True
    return changed


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

    # Ensure spawned process uses the same source as the watcher
    src_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env.get('PYTHONPATH', '')}".strip(os.pathsep)

    if print_only:
        args.append("--print-only")
    if non_interactive:
        args.append("--non-interactive")
    if codex_bypass:
        args.append("--codex-bypass")
    if launcher_timeout > 0:
        args += ["--launcher-timeout", str(launcher_timeout)]

    if print_only:
        subprocess.run(args, check=False, env=env)
        return

    subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


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


_STALE_NO_HANDOFF_HOURS = 4  # archive tasks with no handoff after this many hours

def _auto_archive_stale_tasks(project_dir: str) -> int:
    """Archive tasks stuck in non-terminal states with no handoff file.

    Covers: report_ready, plan_proposed, in_progress with no handoff after
    STALE_NO_HANDOFF_HOURS. These are tasks where agents were dispatched
    but never produced output — dead processes, lost sessions, etc.
    """
    import glob
    from datetime import datetime, timezone

    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            all_tasks = tasks_dao.get_all(conn)
        finally:
            conn.close()
    except Exception:
        return 0

    now = datetime.now(timezone.utc)
    handoff_dir = os.path.join(project_dir, ".superharness", "handoffs")
    archived = 0

    for task in all_tasks:
        if task.status in ("done", "archived", "stopped", "failed"):
            continue
        # Check if task has been in this state long enough
        ts_str = (task.report_ready_at or task.plan_proposed_at or
                  task.in_progress_at or task.created_at or "")
        if not ts_str:
            continue
        try:
            ts = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        hours = (now - ts).total_seconds() / 3600
        if hours < _STALE_NO_HANDOFF_HOURS:
            continue

        # Check if a report/completion handoff exists (plan-phase handoffs don't count)
        pattern = os.path.join(handoff_dir, f"{task.id}*.yaml")
        handoffs = glob.glob(pattern)
        report_handoffs = [h for h in handoffs if "-report-" in os.path.basename(h)
                           or "-done-" in os.path.basename(h)]
        if report_handoffs:
            continue  # Has a completion handoff — agent produced output

        # No handoff after timeout — archive it
        try:
            conn2 = get_connection(project_dir)
            try:
                init_db(conn2)
                tasks_dao.upsert(conn2, tasks_dao.TaskRow(
                    id=task.id, title=task.title, owner=task.owner,
                    status="archived", effort=task.effort,
                    project_path=task.project_path,
                    development_method=task.development_method,
                    acceptance_criteria=task.acceptance_criteria,
                    test_types=task.test_types,
                    out_of_scope=task.out_of_scope,
                    definition_of_done=task.definition_of_done,
                    context=(task.context or "") +
                        f"\n[auto-clean] archived: no handoff after {hours:.0f}h in {task.status}",
                    tdd=task.tdd, version=task.version,
                    created_at=task.created_at, blocked_by=task.blocked_by,
                    parent_id=task.parent_id,
                ))
                conn2.commit()
                archived += 1
                print(f"auto-clean: archived '{task.id}' (no handoff, {hours:.0f}h in {task.status})")
            finally:
                conn2.close()
        except Exception as e:
            print(f"auto-clean: failed to archive '{task.id}': {e}", file=sys.stderr)

    if archived:
        print(f"auto-clean: archived {archived} stale task(s)")
    return archived
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
    
    # Must be auto_dispatch AND (autonomous OR ai_driven) to start new plans automatically
    autonomy = profile.get("autonomy", "ai_driven")
    if not profile.get("auto_dispatch") or autonomy not in ("autonomous", "ai_driven"):
        return 0

    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")

    tasks = _load_tasks(project_dir)
    if not tasks:
        return 0

    inbox_items: list[dict] = []
    try:
        from superharness.engine.state_reader import get_inbox_items
        inbox_items = get_inbox_items(project_dir)
    except Exception:
        inbox_items = []

    added = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_item_ids: set[str] = set()

    # Build a set of archived parent task IDs so subtasks can be skipped.
    archived_ids = {str(t.get("id", "")) for t in tasks if isinstance(t, dict) and t.get("status") == "archived"}

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("status") != "todo":
            continue

        task_id = str(task.get("id", ""))
        if not task_id:
            continue

        # Skip subtasks whose parent is archived (e.g. verify.foo.1 when verify.foo is archived).
        parent_id = ".".join(task_id.rsplit(".", 1)[:-1]) if "." in task_id else ""
        if parent_id and parent_id in archived_ids:
            continue

        if task_id in active_tasks:
            continue

        if not _deps_satisfied_from_tasks(tasks, task_id):
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
            "plan_only": True,
        }
        inbox_items.append(new_item)
        active_tasks.add(task_id)
        new_item_ids.add(item_id)
        added += 1
        print(f"auto-dispatch: enqueued todo {task_id} for planning → {owner} (item {item_id})")

    if added > 0:
        new_items = [i for i in inbox_items if i.get("id") in new_item_ids]
        _sqlite_mirror_inbox_enqueue(project_dir, new_items, now)

    return added


_PEER_AGENTS: dict[str, str] = {
    "claude-code": "gemini-cli",  # Claude proposes → Gemini reviews
    "gemini-cli":  "codex-cli",   # Gemini proposes → Codex reviews
    "codex-cli":   "claude-code", # Codex proposes → Claude reviews
}

_PEER_REVIEW_PROMPT = """Review this plan and approve or reject it.

The task owner ({owner}) proposed a plan for: {task_title}

Acceptance criteria:
{criteria}

Your job as peer reviewer (max-tier model):
1. Read the plan handoff file at .superharness/handoffs/{task_id}*.yaml
2. Check that the plan:
   - Has a complete TDD block (red/green/refactor)
   - Addresses each acceptance criterion
   - Has a risks section
   - Has no TODO placeholders
   - Is feasible in the estimated effort ({effort})

3. Write a 1-sentence verdict: APPROVED or REJECTED with reason.
4. If APPROVED, the task advances to implementation automatically.
5. If REJECTED, the task returns to todo for re-planning.

Verdict:"""

def _auto_peer_approve_plans(project_dir: str) -> int:
    """Find plan_proposed tasks and dispatch to a different max-tier agent for review.

    Never auto-approves without peer review. The peer must be a different agent
    at max tier to ensure impartial judgment. If the peer is unavailable, the
    task stays plan_proposed for operator review.

    Returns count of review tasks enqueued.
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

    # Only run when auto-approve is enabled (now means "use peer review")
    if not profile.get("auto_approve_plans"):
        return 0
    autonomy = profile.get("autonomy", "ai_driven")
    if autonomy not in ("autonomous", "ai_driven"):
        return 0

    tasks = _load_tasks(project_dir)
    if not tasks:
        return 0

    # Get active inbox items to avoid double-dispatch
    active_tasks: set[str] = set()
    try:
        from superharness.engine.state_reader import get_inbox_items
        for item in get_inbox_items(project_dir):
            if isinstance(item, dict) and item.get("status") in ("pending", "launched", "running", "paused"):
                task_id = item.get("task", item.get("task_id", ""))
                if task_id:
                    active_tasks.add(str(task_id))
    except Exception:
        pass

    enqueued = 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if task.get("status") != "plan_proposed":
            continue
        task_id = str(task.get("id", ""))
        if not task_id:
            continue
        if task_id in active_tasks:
            continue  # Already has an active inbox item

        owner = str(task.get("owner") or "claude-code")
        peer = _PEER_AGENTS.get(owner, "gemini-cli")

        # Only dispatch if peer is different from owner
        if peer == owner:
            continue

        # Build review prompt
        criteria = task.get("acceptance_criteria") or []
        criteria_str = "\n".join(f"  - {c}" for c in criteria) if criteria else "  (none)"
        review_prompt = _PEER_REVIEW_PROMPT.format(
            owner=owner,
            task_title=task.get("title", task_id),
            criteria=criteria_str,
            effort=task.get("effort", "medium"),
            task_id=task_id,
        )

        # Enqueue to peer agent as plan-only review
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import inbox_dao
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                item_id = f"peer-review-{task_id.replace('.','-')}-{uuid.uuid4().hex[:8]}"
                inbox_dao.enqueue(
                    conn,
                    id=item_id,
                    task_id=task_id,
                    target_agent=peer,
                    priority=1,  # high priority
                    max_retries=2,
                    project_path=project_dir,
                    plan_only=True,  # review only, don't implement
                    now=now,
                )
                conn.commit()
                enqueued += 1
                print(f"peer-approve: dispatched '{task_id}' plan review → {peer}")
            finally:
                conn.close()
        except Exception as e:
            print(f"peer-approve: failed to enqueue '{task_id}': {e}", file=sys.stderr)

    if enqueued:
        print(f"peer-approve: {enqueued} plan(s) dispatched for peer review")
    return enqueued


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


def _select_reviewers(task: dict, candidates: list[str], profile: dict) -> list[str]:
    """Filter candidate reviewers based on cross-pollination and model-tier gates."""
    from superharness.engine.model_budget import reviewer_meets_tier, AGENT_DEFAULT_TIERS
    
    owner = str(task.get("owner", ""))
    # author tier: 1. task field, 2. owner default, 3. standard
    author_tier = str(task.get("model_tier") or "")
    if not author_tier:
        author_tier = AGENT_DEFAULT_TIERS.get(owner, "standard")
    
    # 1. Cross-pollination guard: owner cannot review own task
    peers = [a for a in candidates if a != owner]
    
    # 2. Model-tier gate: reviewer must be >= author tier
    qualified = [
        a for a in peers 
        if reviewer_meets_tier(a, author_tier, profile)
    ]
    
    return qualified


def _trigger_auto_review(project_dir: str, task_id: str, reviewers: list[str]) -> bool:
    """Transition task to review_requested and enqueue multiple reviewers."""
    from superharness.engine.contract_io import write_contract
    import yaml as _yaml
    import subprocess
    
    # 1. Enqueue each reviewer first (while task is still in report_ready)
    success_count = 0
    enqueued = []
    import time
    for target in reviewers:
        try:
            cmd = [
                sys.executable, "-m", "superharness.commands.inbox_enqueue",
                "--project", project_dir,
                "--to", target,
                "--task", task_id,
                "--priority", "1",
                "--force-reassign",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                success_count += 1
                enqueued.append(target)
            else:
                print(f"auto-review: failed to enqueue {task_id} for {target}: {result.stdout.strip()} {result.stderr.strip()}", file=sys.stderr)
            # Small sleep to ensure file-based inbox lock settles
            time.sleep(0.1)
        except Exception as e:
            print(f"auto-review: error enqueuing {task_id} for {target}: {e}", file=sys.stderr)
            
    if success_count == 0:
        return False

    # 2. Update contract status to review_requested
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    try:
        with open(contract_file, encoding="utf-8") as f:
            doc = _yaml.safe_load(f.read()) or {}
        
        found = False
        for t in doc.get("tasks", []):
            if isinstance(t, dict) and t.get("id") == task_id:
                t["status"] = "review_requested"
                t["review_requested_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                found = True
                break
        
        if found:
            write_contract(contract_file, doc)
        else:
            print(f"auto-review: task {task_id} not found in contract during status update", file=sys.stderr)
            return False
    except Exception as e:
        print(f"auto-review: failed to update contract for {task_id}: {e}", file=sys.stderr)
        return False
        
    print(f"auto-review: triggered reviews for {task_id} via {', '.join(enqueued)}")
    return True


def _auto_close_review_passed(project_dir: str) -> None:
    """Auto-close review_requested tasks when a reviewer submits a verdict report.

    Scans inbox for items with status==done and outcome containing "LGTM" or "REJECTED".
    """
    import yaml as _yaml
    import re as _re
    from superharness.commands.close import close_task
    from superharness.engine.state_writer import mirror_task_dict

    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    profile: dict = {}
    if os.path.isfile(profile_file):
        try:
            with open(profile_file, encoding="utf-8") as _f:
                profile = _yaml.safe_load(_f.read()) or {}
        except Exception:
            return

    # Same opt-in rule as _auto_close_report_ready
    auto_close = profile.get("auto_close", profile.get("autonomy") == "autonomous")
    if not auto_close:
        return

    tasks = _load_tasks(project_dir)
    if not tasks:
        return

    from superharness.engine import state_reader as _sr
    try:
        inbox_items = _sr.get_inbox_items(project_dir)
    except Exception:
        return

    for task in tasks:
        if str(task.get("status")) != "review_requested":
            continue
        task_id = str(task.get("id"))

        # Detect LGTM/REJECTED in any done inbox item for this task
        verdict = ""
        reviewer = "reviewer"
        for item in inbox_items:
            if not isinstance(item, dict):
                continue
            if item.get("task") == task_id and item.get("status") == "done":
                outcome_raw = item.get("outcome")
                
                # F14: If outcome missing from item, check handoffs as fallback
                if not outcome_raw:
                    try:
                        history = _sr.get_handoffs(project_dir, task_id=task_id)
                        if history:
                            # Check the latest report/handoff from this agent
                            agent = str(item.get("to") or "")
                            latest = next((h for h in history if h.get("from_agent") == agent), None)
                            if latest:
                                outcome_raw = str(latest.get("content") or "")
                    except Exception:
                        pass

                if not outcome_raw:
                    continue

                outcome_str = str(outcome_raw).upper()
                
                # Check 1: Structured YAML verdict (highest precision)
                if isinstance(outcome_raw, str) and ("review_verdict:" in outcome_raw or "verdict:" in outcome_raw):
                    try:
                        # Try full YAML load first
                        parsed = _yaml.safe_load(outcome_raw)
                        if isinstance(parsed, dict):
                            v_val = str(parsed.get("review_verdict") or parsed.get("verdict") or "").lower()
                            if v_val in ("lgtm", "rejected", "fail"):
                                verdict = "lgtm" if v_val == "lgtm" else "rejected"
                                reviewer = str(item.get("to") or "reviewer")
                                break
                    except Exception:
                        # Fallback to regex if YAML load fails (e.g. mixed content)
                        pass

                # Check 2: Regex extraction (robust against mixed text/YAML)
                if not verdict and isinstance(outcome_raw, str):
                    m = _re.search(r"(?:review_verdict|verdict):\s*(lgtm|rejected|fail)", outcome_raw, _re.IGNORECASE)
                    if m:
                        v_val = m.group(1).lower()
                        verdict = "lgtm" if v_val == "lgtm" else "rejected"
                        reviewer = str(item.get("to") or "reviewer")
                        break

                # Check 3: Simple string match (legacy fallback)
                if not verdict:
                    if "LGTM" in outcome_str:
                        verdict = "lgtm"
                        reviewer = str(item.get("to") or "reviewer")
                        break
                    elif "REJECTED" in outcome_str:
                        verdict = "rejected"
                        reviewer = str(item.get("to") or "reviewer")
                        break

        if verdict == "lgtm":
            print(f"auto-close: review passed for '{task_id}' (detected LGTM from {reviewer})")
            
            # 1. Transition to review_passed first (required by close_task gate)
            from superharness.engine.state_writer import set_task_status
            set_task_status(project_dir, task_id, "review_passed")

            # 2. Call close_task
            contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
            try:
                close_task(
                    contract_file=contract_file,
                    task_id=task_id,
                    actor=reviewer,
                    summary=f"Review passed: detected LGTM in {reviewer} report.",
                    skip_verify=True,
                )
            except Exception as e:
                print(f"auto-close: failed to close task '{task_id}': {e}", file=sys.stderr)

        elif verdict == "rejected":
            print(f"auto-close: review REJECTED for '{task_id}' (detected REJECTION from {reviewer})")
            from superharness.engine.state_writer import set_task_status
            if set_task_status(project_dir, task_id, "review_failed"):
                # Append to ledger
                ledger_file = os.path.join(project_dir, ".superharness", "ledger.md")
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                line = f"- {ts} — watcher — REJECTED: {task_id} review failed by {reviewer}\n"
                try:
                    with open(ledger_file, "a", encoding="utf-8") as f:
                        f.write(line)
                except Exception:
                    pass


def _auto_close_report_ready(project_dir: str) -> None:
    """Auto-close report_ready tasks whose latest report handoff has tests_passed: true.

    Only runs when auto_close: true in profile.yaml (defaults to autonomy=autonomous).
    Calls close_task(skip_verify=True) with actor='watcher'.
    """
    import glob
    import yaml as _yaml

    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    profile: dict = {}
    if os.path.isfile(profile_file):
        try:
            with open(profile_file, encoding="utf-8") as _f:
                profile = _yaml.safe_load(_f.read()) or {}
        except Exception:
            return

    # Require explicit opt-in OR autonomy=autonomous
    auto_close = profile.get("auto_close", profile.get("autonomy") == "autonomous")
    if not auto_close:
        return

    # Read tasks from SQLite via state_reader (post-migration).
    tasks: list[dict] = _load_tasks(project_dir)
    if not tasks:
        return

    handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
    close_count = 0

    for task in tasks:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "")) != "report_ready":
            continue
        task_id = str(task.get("id", ""))
        if not task_id:
            continue

        # Find the latest report handoff for this task
        pattern = os.path.join(handoffs_dir, f"*{task_id}*report*")
        candidates = sorted(glob.glob(pattern), reverse=True)
        # Also check phase=report handoffs not named with "report"
        pattern2 = os.path.join(handoffs_dir, f"*{task_id}*.yaml")
        for path in sorted(glob.glob(pattern2), reverse=True):
            if path not in candidates:
                candidates.append(path)

        handoff: dict = {}
        for path in candidates:
            try:
                with open(path, encoding="utf-8") as _f:
                    h = _yaml.safe_load(_f.read()) or {}
                if str(h.get("task", "")) == task_id and h.get("phase") == "report":
                    handoff = h
                    break
            except Exception:
                continue

        if not handoff:
            continue
        # Require tests_passed only when auto_close was inferred from autonomy,
        # not when explicitly set — explicit opt-in trusts the operator.
        auto_close_explicit = "auto_close" in profile
        if not handoff.get("tests_passed") and not auto_close_explicit:
            continue

        # iter 6: report verification gate. Stamps verification_failures on
        # the task and routes per suggested_action.
        try:
            from superharness.engine.report_verifier import verify_report as _verify_report
            verification = _verify_report(handoff, task, project_dir)
            if not verification.passed:
                # Stamp verification_failures so dashboard surfaces them
                task["verification_failures"] = verification.failures
                # Persist verification failures to SQLite
                try:
                    from superharness.engine.state_writer import mirror_task_dict
                    mirror_task_dict(project_dir, task)
                except Exception:
                    pass
                if verification.suggested_action == "fail":
                    print(f"auto-close: task '{task_id}' failed verification: " + "; ".join(verification.failures))
                    # Leave for operator (do not auto-fail to avoid surprise)
                else:
                    print(f"auto-close: task '{task_id}' needs operator review: " + "; ".join(verification.failures))
                continue
        except Exception as e:
            print(f"Warning: report verification skipped: {e}", file=sys.stderr)

        # NEW: Auto-review logic (Human-in-the-loop bypass)
        budget_cfg = profile.get("budget", {})
        auto_review_all = bool(budget_cfg.get("auto_review_all", False))
        threshold = float(budget_cfg.get("auto_review_usd_threshold", 0.0))
        cost_usd = float(handoff.get("cost_usd", 0.0))
        peer_reviewers = profile.get("peer_reviewers", [])
        autonomy = profile.get("autonomy", "ai_driven")

        # Autonomous Peer Review selection (cross-pollination)
        if not peer_reviewers and autonomy == "ai_driven":
            known_agents = ["claude-code", "codex-cli", "gemini-cli", "opencode"]
            owner = str(task.get("owner", ""))
            peers = [a for a in known_agents if a != owner]
            if peers:
                peer_reviewers = [peers[0]]

        if peer_reviewers and (auto_review_all or (threshold > 0 and cost_usd <= threshold) or autonomy == "ai_driven"):
            # Reasoning: Reviewer must use a higher or equal model tier than the author
            author_tier = str(task.get("model_tier") or "standard")
            if author_tier == "mini":
                task["model_tier"] = "standard"  # Upgrade to at least standard for review
            
            if _trigger_auto_review(project_dir, task_id, peer_reviewers):
                # Persist tier upgrade to SQLite
                try:
                    from superharness.engine.state_writer import mirror_task_dict
                    mirror_task_dict(project_dir, task)
                except Exception:
                    pass
                continue  # Task moved to review_requested, skip auto-close

        # All gates passed — auto-close via SQLite
        try:
            from superharness.engine.db import get_connection as _gc3, init_db as _idb3
            from superharness.engine import tasks_dao as _td3
            conn3 = _gc3(project_dir)
            try:
                _idb3(conn3)
                existing = _td3.get(conn3, task_id)
                if existing:
                    # Build review context
                    outcome = str(handoff.get("outcome") or "auto-closed by watcher")
                    review_note = (
                        f"\n[auto-mode review] Task completed by {existing.owner or 'agent'}. "
                        f"Outcome: {outcome[:200]}. "
                        f"Review: verify changes, check tests pass, approve or request changes."
                    )
                    new_context = (existing.context or "") + review_note
                    _td3.upsert(conn3, _td3.TaskRow(
                        id=task_id, title=existing.title,
                        owner=existing.owner or "watcher", status="done",
                        effort=existing.effort, project_path=project_dir,
                        development_method=existing.development_method,
                        acceptance_criteria=existing.acceptance_criteria,
                        test_types=existing.test_types,
                        out_of_scope=existing.out_of_scope,
                        definition_of_done=existing.definition_of_done,
                        context=new_context, tdd=existing.tdd,
                        version=existing.version + 1,
                        created_at=existing.created_at,
                        blocked_by=existing.blocked_by,
                        parent_id=existing.parent_id,
                        report_ready_at=existing.report_ready_at,
                    ))
                    conn3.commit()
                    close_count += 1
                    summary = str(handoff.get("outcome") or "auto-closed by watcher")
                    print(f"auto-close: '{task_id}' → done: {summary.split(chr(10))[0][:120]}")
            finally:
                conn3.close()
        except Exception as exc:
            print(f"auto-close: failed to close '{task_id}': {exc}", file=sys.stderr)


    if close_count:
        _fire_hook("task:completed", {"count": close_count}, project_dir)
    print(f"auto-close: closed {close_count} task(s)")


def _auto_retry_failed(project_dir: str) -> None:
    """Auto-retry failed inbox items that have retries remaining.

    Runs when auto_retry: true in profile.yaml (or autonomy=autonomous).
    Items with retry_count >= max_retries are left as failed — permanent
    failures surface in the dashboard for operator review.
    """
    import yaml as _yaml
    from superharness.engine.inbox import _inbox_lock

    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    profile: dict = {}
    if os.path.isfile(profile_file):
        try:
            with open(profile_file, encoding="utf-8") as _f:
                profile = _yaml.safe_load(_f.read()) or {}
        except Exception:
            return

    auto_retry = profile.get("auto_retry", profile.get("autonomy") == "autonomous")
    if not auto_retry:
        return

    # Reset failed items directly in SQLite
    _auto_retry_failed_sqlite(project_dir)


def _auto_retry_failed_sqlite(project_dir: str) -> None:
    """Reset failed SQLite inbox items that still have retries remaining. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        now = _now_utc()
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            failed = inbox_dao.get_all(conn, status="failed")
            for row in failed:
                if row.retry_count < row.max_retries:
                    new_count = row.retry_count + 1
                    # Preserve the original failure reason so operator can see it
                    preserved_reason = row.failed_reason or "auto-retry (reason unavailable)"
                    inbox_dao.set_retry(conn, row.id, new_count, preserved_reason, now)
                    # Discussion round tasks must not be plan_only
                    if "/round-" in str(row.task_id) or "round-" in str(row.task_id):
                        conn.execute("UPDATE inbox SET plan_only=0 WHERE id=?", (row.id,))
                    print(
                        f"auto-retry (sqlite): re-queued '{row.task_id}' "
                        f"(attempt {new_count}/{row.max_retries})"
                    )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"auto-retry (sqlite): error: {exc}", file=sys.stderr)


_AGENT_FALLBACK: dict[str, list[str]] = {
    "claude-code": ["gemini-cli", "codex-cli"],
    "gemini-cli":  ["claude-code", "codex-cli"],
    "codex-cli":   ["claude-code", "gemini-cli"],
}

_RECOVERY_MAX = 2  # max recovery attempts before escalating to operator

def _auto_recover_exhausted_failures_sqlite(project_dir: str) -> None:
    """Recover failed inbox items that have exhausted retries.

    Uses the failure_classifier to decide if recovery is possible:
      - permanent_block / no_op → skip (different agent won't help)
      - quota / transient / agent_crash / unknown → re-enqueue to a fallback agent

    Items already recovered RECOVERY_MAX times are escalated to operator:
      marks the parent task as blocked with failure_context.
    Never raises.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao, tasks_dao
        now = _now_utc()
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            failed = inbox_dao.get_all(conn, status="failed")
            recovered = 0
            escalated = 0

            for row in failed:
                if row.retry_count < row.max_retries:
                    continue  # _auto_retry_failed handles these

                # Parse recovery_count from failed_reason or use 0
                recovery_count = 0
                reason = (row.failed_reason or "").lower()
                # Check for existing recovery markers stored in reason text
                import re
                rc_match = re.search(r"recovery_(\d+)", reason)
                if rc_match:
                    recovery_count = int(rc_match.group(1))

                # Skip permanent failures — agent routing won't help
                # But revert stuck in_progress tasks so they can be re-dispatched
                if "permanent_block" in reason or "no_op" in reason or "permanent block" in reason:
                    task_pb = tasks_dao.get(conn, row.task_id)
                    if task_pb and task_pb.status == "in_progress":
                        try:
                            gate_reason = row.failed_reason or "lifecycle gate rejected"
                            conn.execute(
                                "UPDATE tasks SET status='waiting_input', in_progress_at=NULL, "
                                "failed_reason=? WHERE id=?",
                                (gate_reason, row.task_id),
                            )
                            # Mark inbox as done so it doesn't block re-dispatch
                            conn.execute("UPDATE inbox SET status='done' WHERE id=?", (row.id,))
                            print(
                                f"auto-recover: permanent block escalated '{row.task_id}' "
                                f"in_progress → waiting_input (lifecycle gate)"
                            )
                            recovered += 1
                        except Exception:
                            pass
                    continue

                # Skip if parent task is no longer dispatch-ready
                task = tasks_dao.get(conn, row.task_id)
                if task is None or task.status in ("done", "stopped", "archived"):
                    continue

                # Determine fallback agent
                current_agent = row.target_agent
                fallback_agents = _AGENT_FALLBACK.get(current_agent, ["claude-code", "gemini-cli"])
                next_agent = fallback_agents[0]  # try first fallback

                # If already recovered too many times, escalate with root cause analysis
                if recovery_count >= _RECOVERY_MAX:
                    reason_lower = (row.failed_reason or "").lower()

                    agents_tried: list[str] = []
                    rc_matches = re.findall(r"_to_(\S+)", reason_lower)
                    agents_tried = [row.target_agent] + rc_matches
                    agents_tried = list(dict.fromkeys(agents_tried))

                    is_architecture_bug = (
                        "permanent_block" in reason_lower
                        or "command not found" in reason_lower
                        or "syntax error" in reason_lower
                        or "unbound variable" in reason_lower
                    )

                    if is_architecture_bug:
                        context_note = (
                            f"\n[auto-recovery] INFRA ESCALATION: task failed on "
                            f"{', '.join(agents_tried)} with: "
                            f"{row.failed_reason or 'unknown error'}. "
                            f"Check launcher logs, CLI availability, and superharness hooks."
                        )
                        new_status = "waiting_input"
                        # Record to failures ledger for diagnostics
                        try:
                            from superharness.engine import failures_dao
                            failures_dao.record(
                                conn,
                                agent=row.target_agent,
                                error=f"[auto-recovery] infra escalation: "
                                      f"task {row.task_id} failed on {agents_tried}",
                                details={"task_id": row.task_id, "agents": agents_tried,
                                        "reason": row.failed_reason},
                            )
                        except Exception:
                            pass
                # Recover: re-enqueue to fallback agent with raw SQL
                new_recovery = recovery_count + 1
                new_reason = f"recovery_{new_recovery}:{current_agent}_to_{next_agent}"
                conn.execute(
                    """UPDATE inbox
                       SET status = 'pending', retry_count = 0,
                           max_retries = max_retries + 1,
                           target_agent = ?, failed_reason = ?,
                           pid = NULL, failed_at = NULL
                       WHERE id = ?""",
                    (next_agent, new_reason, row.id)
                )
                print(
                    f"auto-recover: re-routed '{row.task_id}' "
                    f"{current_agent} → {next_agent} "
                    f"(recovery_{new_recovery}/{_RECOVERY_MAX})"
                )
                recovered += 1

            conn.commit()
            if recovered or escalated:
                print(
                    f"auto-recover: {recovered} re-routed, "
                    f"{escalated} escalated to operator"
                )
        finally:
            conn.close()
    except Exception as exc:
        print(f"auto-recover: error: {exc}", file=sys.stderr)


def _reconcile_permanent_blocks(project_dir: str) -> int:
    """Revert in_progress tasks stuck behind permanent-block inbox failures.

    Returns count of tasks reverted.
    Public entry point for the watcher loop and tests.
    Delegates to _auto_recover_exhausted_failures_sqlite.
    """
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao, inbox_dao

    count = 0
    try:
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            failed = inbox_dao.get_all(conn, status="failed")
            for row in failed:
                if row.retry_count < row.max_retries:
                    continue
                reason = (row.failed_reason or "").lower()
                if "permanent_block" not in reason and "no_op" not in reason and "permanent block" not in reason:
                    continue
                task = tasks_dao.get(conn, row.task_id)
                if not task or task.status != "in_progress":
                    continue
                conn.execute(
                    "UPDATE tasks SET status='waiting_input', in_progress_at=NULL, "
                    "failed_reason=? WHERE id=?",
                    (row.failed_reason or "lifecycle gate rejected", row.task_id),
                )
                conn.execute("UPDATE inbox SET status='done' WHERE id=?", (row.id,))
                count += 1
                print(
                    f"reconcile-permanent-block: escalated '{row.task_id}' "
                    f"in_progress → waiting_input"
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        print(f"reconcile-permanent-block: error: {exc}", file=sys.stderr)
    return count


def _check_ship_on_complete_tasks(project_dir: str) -> None:
    """For ship_on_complete tasks at report_ready with no PR URL, mark failed."""
    from superharness.engine import state_reader, state_writer

    try:
        tasks = state_reader.get_tasks(project_dir)
    except Exception:
        return

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
            print(
                f"ship_on_complete: task '{task_id}' reached report_ready without a PR URL "
                f"in handoff outcomes — marking failed.",
                file=sys.stderr,
            )
            state_writer.set_task_status(project_dir, task_id, "failed", from_status="report_ready")


def run_once(
    project_dir: str,
    *,
    to: str = "both",
    non_interactive: bool = True,  # default non-interactive for auto-mode
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


def _fire_hook(event: str, data: dict, project_dir: str | None = None) -> None:
    """Fire an event hook. Never raises."""
    try:
        from superharness.engine.hooks import get_registry
        get_registry().fire(event, data)
    except Exception:
        pass


def _sqlite_singleton_acquire(project_dir: str) -> None:
    """Acquire the SQLite watcher singleton lease. Never raises."""
    try:
        import socket
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import watcher_singleton
        now = _now_utc()
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            watcher_singleton.acquire(
                conn, pid=os.getpid(), hostname=socket.gethostname(), now=now
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _sqlite_singleton_release(project_dir: str) -> None:
    """Release the SQLite watcher singleton lease. Never raises."""
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import watcher_singleton
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            watcher_singleton.release(conn, os.getpid())
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _sqlite_tick(project_dir: str, now: str) -> None:
    """Run SQLite-side per-tick operations: record heartbeat.

    Never raises. Silently skipped if SQLite backend is not initialised yet.
    """
    try:
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import watcher_singleton
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            watcher_singleton.heartbeat(conn, os.getpid(), now)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def _self_diagnosis(project_dir: str) -> list[str]:
    """Check environment health before running auto-mode. Returns list of warnings."""
    warnings = []

    # Check Python has yaml (prevents ModuleNotFoundError)
    try:
        import yaml
    except ImportError:
        warnings.append("MISSING: pyyaml not installed — dispatch will fail")

    # Check SQLite DB exists and is writable
    db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
    if not os.path.isfile(db_path):
        warnings.append(f"MISSING: {db_path} — run shux init or start watcher first")
    elif not os.access(db_path, os.W_OK):
        warnings.append(f"PERMISSION: {db_path} is not writable")

    # Check agent binaries exist
    for agent, binary in [("claude-code", "claude"), ("codex-cli", "codex"), ("gemini-cli", "gemini")]:
        import shutil
        if not shutil.which(binary):
            warnings.append(f"MISSING: {agent} binary '{binary}' not on PATH")

    # Check profile.yaml exists and has required fields
    profile_file = os.path.join(project_dir, ".superharness", "profile.yaml")
    if os.path.isfile(profile_file):
        try:
            profile = yaml.safe_load(open(profile_file).read()) or {}
            if not profile.get("auto_dispatch"):
                warnings.append("CONFIG: auto_dispatch not enabled in profile.yaml")
        except Exception:
            warnings.append("CORRUPT: profile.yaml cannot be parsed")
    else:
        warnings.append("MISSING: profile.yaml — auto-mode needs project config")

    # Log warnings
    if warnings:
        for w in warnings:
            print(f"self-diagnosis: {w}")

    return warnings


def auto_enqueue_todo(project_dir: str) -> int:
    """Scan contract for todo tasks and enqueue them for planning.
    
    Only runs if auto_dispatch=True and autonomy=(autonomous OR ai_driven) in profile.yaml.
    """
    import uuid
    from datetime import datetime, timezone
    from superharness.engine import state_reader, state_writer
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

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

    # autonomy: ai_driven or autonomous allowed for planning
    autonomy = profile.get("autonomy", "ai_driven")
    if autonomy not in ("autonomous", "ai_driven"):
        return 0

    tasks = _load_tasks(project_dir)
    if not tasks:
        return 0

    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    inbox_items = []
    try:
        inbox_items = state_reader.get_inbox_items(project_dir)
    except Exception:
        pass

    # Track tasks already in inbox (active)
    active_tasks: set[str] = set()
    for item in inbox_items:
        if not isinstance(item, dict): continue
        if item.get("status") in ("pending", "launched", "running", "paused"):
            active_tasks.add(str(item.get("task", "")))

    added = 0
    now = _now_utc()
    new_items = []
    
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        for task in tasks:
            if not isinstance(task, dict) or task.get("status") != "todo":
                continue
            task_id = str(task.get("id", ""))
            if not task_id or task_id in active_tasks:
                continue
            
            # Check dependencies
            if not _deps_satisfied_from_tasks(tasks, task_id):
                continue

            # Skip tasks whose deadline has already passed (lifecycle will fail them anyway)
            deadline = task.get("deadline_minutes")
            if deadline:
                try:
                    deadline = int(deadline)
                except (ValueError, TypeError):
                    deadline = None
            if deadline and deadline > 0:
                created = task.get("created_at", "")
                if created:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        t = _dt.fromisoformat(str(created).replace("Z", "+00:00"))
                        now_dt = _dt.now(_tz.utc)
                        age = (now_dt - t).total_seconds() / 60
                        if age >= deadline:
                            continue  # deadline already expired — don't enqueue
                    except (ValueError, TypeError):
                        pass

            owner = str(task.get("owner", "claude-code"))
            item_id = f"auto-{uuid.uuid4().hex[:6]}"
            
            # 1. Mirror task to SQLite if missing
            _ensure_task_in_sqlite(conn, task_id, project_dir, now)
            
            # 2. Enqueue in SQLite
            inbox_dao.enqueue(conn, id=item_id, task_id=task_id,
                              target_agent=owner, priority=2, max_retries=3,
                              project_path=project_dir, plan_only=True, now=now)
            
            new_items.append({
                "id": item_id, "task": task_id, "to": owner, "status": "pending",
                "priority": 2, "retry_count": 0, "max_retries": 3, "created_at": now,
                "project": project_dir, "plan_only": True
            })
            active_tasks.add(task_id)
            added += 1
            print(f"auto-dispatch: enqueued todo {task_id} for planning → {owner}")
        
        conn.commit()
    finally:
        conn.close()

    return added

def auto_enqueue_approved(project_dir: str) -> int:
    """Scan contract for plan_approved tasks and enqueue them.
    
    Only runs if auto_dispatch=True and autonomy=(autonomous OR oversight OR ai_driven) in profile.yaml.
    """
    import uuid
    from datetime import datetime, timezone
    from superharness.engine import state_reader, state_writer
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

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

    # autonomy: ai_driven, oversight, or autonomous allowed for implementation
    autonomy = profile.get("autonomy", "ai_driven")
    if autonomy not in ("autonomous", "oversight", "ai_driven"):
        return 0

    tasks = _load_tasks(project_dir)
    if not tasks:
        return 0

    inbox_file = os.path.join(project_dir, ".superharness", "inbox.yaml")
    inbox_items = []
    try:
        inbox_items = state_reader.get_inbox_items(project_dir)
    except Exception:
        pass

    # Track tasks already in inbox (active)
    active_tasks: set[str] = set()
    for item in inbox_items:
        if not isinstance(item, dict): continue
        if item.get("status") in ("pending", "launched", "running", "paused"):
            active_tasks.add(str(item.get("task", "")))

    # Track per-task failure counts to enforce a retry cap.
    # Without this guard, every failed item exits active_tasks and the next
    # watcher tick creates a fresh item with retry_count=0 — causing an
    # infinite flood of new items for permanently-failing tasks.
    # Prefer SQLite (authoritative in production); fall back to YAML items.
    failed_counts: dict[str, int] = {}
    _default_max_retries = 3
    _db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
    if os.path.isfile(_db_path):
        try:
            _fc = get_connection(project_dir)
            try:
                init_db(_fc)
                for row in _fc.execute(
                    "SELECT task_id, COUNT(*) FROM inbox WHERE status='failed' GROUP BY task_id"
                ).fetchall():
                    failed_counts[str(row[0])] = int(row[1])
            finally:
                _fc.close()
        except Exception:
            pass
    else:
        for item in inbox_items:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "failed":
                tid = str(item.get("task", ""))
                failed_counts[tid] = failed_counts.get(tid, 0) + 1

    added = 0
    now = _now_utc()
    new_items = []

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        for task in tasks:
            if not isinstance(task, dict) or task.get("status") != "plan_approved":
                continue
            task_id = str(task.get("id", ""))
            if not task_id or task_id in active_tasks:
                continue
            # Stop re-enqueueing tasks that have already exhausted their retry budget.
            max_retries = int(task.get("max_retries", _default_max_retries))
            if failed_counts.get(task_id, 0) >= max_retries:
                continue
            
            # Check dependencies
            if not _deps_satisfied_from_tasks(tasks, task_id):
                continue

            # Skip tasks whose deadline has already passed (lifecycle will fail them anyway)
            deadline = task.get("deadline_minutes")
            if deadline:
                try:
                    deadline = int(deadline)
                except (ValueError, TypeError):
                    deadline = None
            if deadline and deadline > 0:
                created = task.get("created_at", "")
                if created:
                    try:
                        from datetime import datetime as _dt, timezone as _tz
                        t = _dt.fromisoformat(str(created).replace("Z", "+00:00"))
                        now_dt = _dt.now(_tz.utc)
                        age = (now_dt - t).total_seconds() / 60
                        if age >= deadline:
                            continue  # deadline already expired — don't enqueue
                    except (ValueError, TypeError):
                        pass

            owner = str(task.get("owner", "claude-code"))
            item_id = f"auto-{uuid.uuid4().hex[:6]}"
            
            # 1. Mirror task to SQLite if missing
            _ensure_task_in_sqlite(conn, task_id, project_dir, now)
            
            # 2. Enqueue in SQLite; catch duplicate if another process raced us.
            try:
                inbox_dao.enqueue(conn, id=item_id, task_id=task_id,
                                  target_agent=owner, priority=2, max_retries=3,
                                  project_path=project_dir, plan_only=False, now=now)
            except Exception as _enq_err:
                # StateError (duplicate) or any other DB error — skip silently.
                active_tasks.add(task_id)
                continue

            new_items.append({
                "id": item_id, "task": task_id, "to": owner, "status": "pending",
                "priority": 2, "retry_count": 0, "max_retries": 3, "created_at": now,
                "project": project_dir, "plan_only": False
            })
            active_tasks.add(task_id)
            added += 1
            print(f"auto-dispatch: enqueued approved {task_id} → {owner}")
        
        conn.commit()
    finally:
        conn.close()

    return added



_LAUNCHER_LOG_MAX_FILES = 200

def _rotate_launcher_logs_if_needed(project_dir: str) -> None:
    """Remove old launcher logs if there are too many. Never raises."""
    import glob
    try:
        log_dir = os.path.join(project_dir, '.superharness', 'launcher-logs')
        if not os.path.isdir(log_dir):
            return
        logs = sorted(glob.glob(os.path.join(log_dir, '*.log')), key=os.path.getmtime)
        if len(logs) > _LAUNCHER_LOG_MAX_FILES:
            to_remove = len(logs) - _LAUNCHER_LOG_MAX_FILES
            for lf in logs[:to_remove]:
                os.remove(lf)
            print(f'disk-guard: removed {to_remove} old launcher log(s) ({len(logs)} -> {_LAUNCHER_LOG_MAX_FILES})')
    except Exception:
        pass
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

    # Self-diagnosis: check environment before running auto-mode
    _self_diagnosis(project_dir)

    # Disk guard: rotate launcher logs if too many (>200 total)
    _rotate_launcher_logs_if_needed(project_dir)

    # SQLite tick: drain dual-write queue + record heartbeat
    _sqlite_tick(project_dir, _now_utc())

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

    # Auto-retry failed inbox items that still have retries remaining
    try:
        _auto_retry_failed(project_dir)
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Auto-recover exhausted failures: re-route to a different agent
    try:
        _auto_recover_exhausted_failures_sqlite(project_dir)
    except Exception as e:
        print(f"Warning: auto_recover_exhausted_failures failed: {e}", file=sys.stderr)

    # Auto-close report_ready tasks with tests_passed: true in their handoff
    try:
        _auto_close_report_ready(project_dir)
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Auto-close review_requested tasks when a reviewer submits a verdict report
    try:
        _auto_close_review_passed(project_dir)
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Auto-close consensus discussions after grace period
    try:
        _auto_close_consensus_discussions(project_dir)
    except Exception as e:
        print(f"Warning: discussion auto-close failed: {e}", file=sys.stderr)

    # Sync cancelled/closed discussions back to contract task status + clean inbox
    try:
        _reconcile_discussion_contract(project_dir)
    except Exception as e:
        print(f"Warning: discussion contract reconciliation failed: {e}", file=sys.stderr)

    # review_requested timeout is handled by reconcile_lifecycle (above, after dispatch reconciliation)

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

    # Auto peer-approve plan_proposed tasks: dispatch to a different max-tier agent for review
    try:
        _auto_peer_approve_plans(project_dir)
    except Exception as e:
        print(f"Warning: peer_approve_plans failed: {e}", file=sys.stderr)

    # Auto-enqueue plan_approved tasks when auto_dispatch=True in profile.yaml
    try:
        auto_enqueue_approved(project_dir)
    except Exception as e:
        print(f"Warning: auto_enqueue_approved failed: {e}", file=sys.stderr)

    # Clean stale tasks with no handoff after timeout
    try:
        _auto_archive_stale_tasks(project_dir)
    except Exception as e:
        print(f"Warning: auto_archive_stale_tasks failed: {e}", file=sys.stderr)

    # Reconcile zombie inbox items (launched but process gone)
    try:
        _reconcile_zombies(project_dir)
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Analyze task logs for stuck agents
    try:
        _analyze_task_logs(project_dir)
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Reconcile paused dead-pid items — read from SQLite, write to SQLite
    try:
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn_paused = get_connection(project_dir)
        try:
            init_db(conn_paused)
            paused_items = [asdict(r) for r in inbox_dao.get_all(conn_paused, status="paused")]
            if _reconcile_paused_dead_pids(paused_items):
                for item in paused_items:
                    if isinstance(item, dict) and item.get("status") != "paused":
                        inbox_dao.update_status(
                            conn_paused, item.get("id", ""),
                            from_status="paused",
                            to_status=item.get("status", "failed"),
                            now=_now_utc()
                        )
                conn_paused.commit()
        finally:
            conn_paused.close()
    except Exception as e:
        print(f"Warning: paused dead-pid reconciliation failed: {e}", file=sys.stderr)

    # iter 7: review escalation — runs before lifecycle reconciler so chain
    # advancement takes priority over the simple revert behavior.
    try:
        from superharness.engine.review_escalation import escalate_stale_reviews
        escalate_stale_reviews(project_dir)
    except Exception as e:
        print(f"Warning: review escalation failed: {e}", file=sys.stderr)

    # Unified lifecycle reconciler (paused timeout, in_progress timeout, and
    # any review_requested without a review_chain that the escalation pass left)
    try:
        from superharness.engine.lifecycle_rules import reconcile_lifecycle
        reconcile_lifecycle(project_dir)
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Proactive session flush: save partial work before lifecycle timeout
    try:
        from superharness.engine.session_flush import check_expiring, flush_task
        expiring = check_expiring(project_dir)
        for task_id in expiring:
            flush_task(project_dir, task_id)
        if expiring:
            print(f"session-flush: flushed {len(expiring)} expiring task(s)")
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))

    # Inbox GC: reconcile stale items against contract
    try:
        _watcher_cycle_count[0] += 1
        _run_gc_if_due(project_dir, _watcher_cycle_count[0])
    except Exception as e:
        print(f"Warning: inbox gc failed: {e}", file=sys.stderr)

    # Auto-delete terminal stale inbox items (status='stale') — they're dead data
    try:
        _auto_delete_stale_inbox(project_dir)
    except Exception as e:
        print(f"Warning: stale inbox cleanup failed: {e}", file=sys.stderr)

    # Cancel pending items for agents without dispatch scripts (will never dispatch)
    try:
        _cancel_undispatchable_agents(project_dir)
    except Exception as e:
        print(f"Warning: undispatchable agent cleanup failed: {e}", file=sys.stderr)

    # Dispatch — check budget before launching agents
    targets = []
    if target == "both":
        try:
            from superharness.engine.adapter_registry import list_adapters
            targets = list_adapters()
        except Exception:
            targets = ["claude-code", "codex-cli", "gemini-cli"]
    else:
        targets = [target]

    # Budget gate: skip dispatch if daily budget is exceeded (strict mode)
    try:
        from superharness.engine.model_budget import check_budget, BudgetStatus
        budget = check_budget(project_dir)
        if budget.status == BudgetStatus.BLOCK:
            print(f"budget-gate: BLOCKED — daily budget exceeded (${budget.used_today:.2f} / ${budget.daily_limit:.2f}). Skipping dispatch.")
            return
        elif budget.status == BudgetStatus.WARN:
            print(f"budget-gate: WARN — {budget.message}")
    except Exception as e:
        _log_watcher_error(project_dir, "watcher", str(e))


    for t in targets:
        # Per-agent budget check: skip agents over their limit
        try:
            from superharness.engine.model_budget import check_agent_budget, BudgetStatus
            agent_budget = check_agent_budget(project_dir, t)
            if agent_budget.status == BudgetStatus.BLOCK:
                print(f"budget-gate: skipping {t} — per-agent budget exceeded (${agent_budget.used_today:.2f} / ${agent_budget.daily_limit:.2f})")
                continue
            elif agent_budget.status == BudgetStatus.WARN:
                print(f"budget-gate: {t} WARN — ${agent_budget.used_today:.2f} / ${agent_budget.daily_limit:.2f}")
        except Exception as e:
            _log_watcher_error(project_dir, "watcher", str(e))

        # Loop detection: stateful warn→block using LoopGuard
        try:
            from superharness.engine.loop_detector import detect_loop, LoopGuard
            sh_dir = os.path.join(project_dir, ".superharness")
            guard = LoopGuard(state_dir=sh_dir)
            log_dir = os.path.join(sh_dir, "launcher-logs")
            _loop_action = "allow"
            if os.path.isdir(log_dir):
                for lf in sorted(os.listdir(log_dir), reverse=True):
                    if lf.endswith(".log") and t in lf:
                        loop = detect_loop(os.path.join(log_dir, lf))
                        decision = guard.check(t, loop)
                        _loop_action = decision["action"]
                        if _loop_action == "warn":
                            print(f"loop-guard: WARN {t} — {decision['reason']} (pattern: {loop['pattern']})")
                        elif _loop_action == "block":
                            from superharness.engine.policy_gate import check_agent_policy
                            check_agent_policy(t, loop_detected=True)
                            print(f"loop-guard: BLOCKED {t} — {decision['reason']} (pattern: {loop['pattern']})")
                        break
            if _loop_action == "block":
                continue
        except Exception as e:
            _log_watcher_error(project_dir, "watcher", str(e))

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


_TASK_LOG_STALE_MINUTES = 15  # mark as failed if no activity for this long


def _analyze_task_logs(project_dir: str) -> None:
    """Check launched task logs for activity. Stale tasks get marked failed."""
    import glob
    from dataclasses import asdict
    from datetime import datetime, timezone
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        launched = inbox_dao.get_all(conn, status="launched")
        if not launched:
            return

        now = datetime.now(timezone.utc)
        launcher_logs = os.path.join(project_dir, ".superharness", "launcher-logs")
        escalated = 0

        for item in launched:
            d = asdict(item)
            launched_at = d.get("launched_at", "")
            if not launched_at:
                continue
            try:
                lt = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
                age_minutes = (now - lt).total_seconds() / 60
            except (ValueError, TypeError):
                continue

            if age_minutes < _TASK_LOG_STALE_MINUTES:
                continue  # not stale yet

            # Find log file for this task
            task_id = item.task_id.replace("/", "_")
            agent = item.target_agent
            log_pattern = os.path.join(launcher_logs, f"*{task_id}*{agent}*.log")

            logs = sorted(glob.glob(log_pattern), key=os.path.getmtime, reverse=True)
            if not logs:
                # No log file at all → likely never started
                inbox_dao.update_status(conn, item.id, from_status="launched", to_status="failed", now=_now_utc())
                print(f"log-analyzer: '{item.task_id}' → failed (no log file after {int(age_minutes)}m)")
                escalated += 1
                continue

            # Check latest log for activity
            latest_log = logs[0]
            try:
                log_mtime = datetime.fromtimestamp(os.path.getmtime(latest_log), tz=timezone.utc)
                inactive_minutes = (now - log_mtime).total_seconds() / 60
            except Exception:
                inactive_minutes = 0

            # Check for git changes as activity signal
            has_activity = False
            try:
                import subprocess
                r = subprocess.run(
                    ["git", "diff", "--stat", "HEAD"],
                    capture_output=True, text=True, check=False, timeout=5,
                    cwd=project_dir
                )
                if r.stdout.strip():
                    has_activity = True
            except Exception:
                pass

            if has_activity:
                print(f"log-analyzer: '{item.task_id}' active (files changing, {int(age_minutes)}m elapsed)")
                continue

            if inactive_minutes >= _TASK_LOG_STALE_MINUTES:
                inbox_dao.update_status(conn, item.id, from_status="launched", to_status="failed", now=_now_utc())
                print(f"log-analyzer: '{item.task_id}' → failed (no log activity for {int(inactive_minutes)}m, {int(age_minutes)}m total)")
                escalated += 1

        if escalated:
            print(f"log-analyzer: {escalated} stale task(s) marked failed")
            conn.commit()
    finally:
        conn.close()
def _reconcile_zombies(project_dir: str, max_age_seconds: int = 300) -> int:
    """Reconcile launched inbox items that have no running process.

    Checks in order:
    1. Contract says done → mark inbox done
    2. PID set but process dead → mark inbox failed
    2b. PID alive + plan-only + age > 15 min → kill and fail
    2c. PID alive + non-plan-only + age > 2 hours → kill and fail
    3. No PID + launched > max_age_seconds ago → mark inbox failed

    Returns count of reconciled items.
    """
    import yaml as _yaml

    harness = os.path.join(project_dir, ".superharness")
    inbox_file = os.path.join(harness, "inbox.yaml")
    contract_file = os.path.join(harness, "contract.yaml")

    # Read from SQLite via state_reader (post-migration)
    items = []
    try:
        from superharness.engine.state_reader import get_inbox_items
        items = get_inbox_items(project_dir)
    except Exception:
        if os.path.exists(inbox_file):
            with open(inbox_file, encoding="utf-8") as _f:
                items = _yaml.safe_load(_f.read()) or []
    if not isinstance(items, list) or not items:
        return 0

    contract_statuses: dict[str, str] = {}
    try:
        from superharness.engine.state_reader import get_tasks
        for t in get_tasks(project_dir):
            if isinstance(t, dict) and t.get("id"):
                contract_statuses[str(t["id"])] = str(t.get("status", ""))
    except Exception:
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
            # Check 2b: plan-only task alive but timed out → kill and fail
            elif item.get("plan_only") and launched_at:
                _PLAN_ONLY_TIMEOUT = 900  # 15 minutes
                try:
                    lt = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
                    age = (now - lt).total_seconds()
                    if age > _PLAN_ONLY_TIMEOUT:
                        try:
                            os.kill(pid_int, signal.SIGTERM)
                        except Exception:
                            pass
                        item["status"] = "failed"
                        item["failed_at"] = _now_utc()
                        item["pid"] = ""
                        item["failed_reason"] = f"plan-only timeout ({int(age)}s > {_PLAN_ONLY_TIMEOUT}s)"
                        reconciled += 1
                        changed = True
                        print(f"zombie-reconcile: {item_id} ({task_id}) → failed (plan-only timeout, {int(age)}s)")
                except (ValueError, TypeError):
                    pass
            # Check 2c: non-plan-only task alive but running beyond max wall-clock cap → kill and fail
            elif launched_at:
                _MAX_LAUNCH_AGE_SECONDS = 7200  # 2 hours
                try:
                    lt = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
                    age = (now - lt).total_seconds()
                    if age > _MAX_LAUNCH_AGE_SECONDS:
                        try:
                            os.kill(pid_int, signal.SIGTERM)
                        except Exception:
                            pass
                        item["status"] = "failed"
                        item["failed_at"] = _now_utc()
                        item["pid"] = ""
                        item["failed_reason"] = f"max launch age exceeded ({int(age)}s > {_MAX_LAUNCH_AGE_SECONDS}s)"
                        reconciled += 1
                        changed = True
                        print(f"zombie-reconcile: {item_id} ({task_id}) → failed (max age, {int(age)}s)")
                except (ValueError, TypeError):
                    pass
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
        # Write changes directly to SQLite (post-migration)
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            for item in items:
                if isinstance(item, dict):
                    item_id = str(item.get("id", ""))
                    new_status = item.get("status", "")
                    if item_id and new_status:
                        try:
                            row = inbox_dao.get(conn, item_id)
                            if row:
                                inbox_dao.update_status(
                                    conn, item_id,
                                    from_status="launched",
                                    to_status=new_status,
                                    now=_now_utc()
                                )
                        except Exception:
                            # Fallback: direct SQL update
                            conn.execute(
                                "UPDATE inbox SET status=? WHERE id=?",
                                (new_status, item_id)
                            )
            conn.commit()
        finally:
            conn.close()

    return reconciled


def _reconcile_discussion_contract(project_dir: str) -> int:
    """Find in_progress tasks whose linked discussion is terminal.

    When a discussion is cancelled or closed via CLI (not dashboard), the contract
    task linked to it stays in_progress. This reconciler catches that gap.
    Reads discussion state from SQLite (post-YAML removal).
    Returns count of tasks updated.
    """
    from superharness.engine import state_reader, state_writer
    from superharness.engine.db import get_connection, init_db

    terminal = {"cancelled", "closed", "consensus", "deadlock", "failed"}

    # Collect terminal discussion IDs from SQLite
    terminal_disc_ids: set[str] = set()
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = conn.execute(
            "SELECT id FROM discussions WHERE status IN (?, ?, ?, ?, ?)",
            tuple(terminal),
        ).fetchall()
        terminal_disc_ids = {r["id"] for r in rows}
    except Exception:
        return 0
    finally:
        conn.close()

    if not terminal_disc_ids:
        return 0

    try:
        tasks = state_reader.get_tasks(project_dir)
    except Exception:
        return 0

    updated = 0
    for task in tasks:
        if not isinstance(task, dict) or task.get("status") != "in_progress":
            continue
        tid = str(task.get("id", ""))
        for disc_id in terminal_disc_ids:
            if tid.startswith(disc_id + "/") or tid == disc_id:
                if state_writer.set_task_status(project_dir, tid, "archived", from_status="in_progress"):
                    updated += 1
                    print(f"discussion-reconcile: {tid} → archived (discussion {disc_id} is terminal)")
                break

    # Always clean up inbox items for terminal discussions (even if tasks already archived)
    if terminal_disc_ids:
        try:
            from superharness.engine.state_reader import get_inbox_items
            inbox = get_inbox_items(project_dir)
            inbox_cleaned = 0
            for item in inbox:
                if not isinstance(item, dict):
                    continue
                iid = str(item.get("id", ""))
                itask = str(item.get("task", item.get("task_id", "")))
                istatus = str(item.get("status", ""))
                if istatus not in ("pending", "launched", "running", "paused"):
                    continue
                for disc_id in terminal_disc_ids:
                    if itask.startswith(disc_id + "/") or itask == disc_id:
                        state_writer.set_inbox_status(project_dir, iid, "done")
                        inbox_cleaned += 1
                        break
            if inbox_cleaned > 0:
                print(f"discussion-reconcile: cleaned {inbox_cleaned} inbox item(s) for terminal discussions")
        except Exception as e:
            print(f"discussion-reconcile: inbox cleanup failed: {e}", file=sys.stderr)

    return updated


_CONSENSUS_GRACE_MINUTES = 60  # auto-close consensus discussions after 1h


def _auto_close_consensus_discussions(project_dir: str) -> int:
    """Close discussions that have been in consensus state beyond the grace period.

    Reads discussion state from SQLite (post-YAML removal).
    Returns count of discussions closed.
    """
    from datetime import datetime, timezone
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    closed = 0

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = discussions_dao.get_all(conn, status="consensus")
        if not rows:
            return 0

        for row in rows:
            disc_id = row.id

            # If closed_at is already stamped but status wasn't updated, close immediately
            # (repairs SQLite-only drift where close() set closed_at but status stayed consensus)
            age_min: int | None = None
            if row.closed_at:
                pass  # fall through to close below
            else:
                # Use created_at for age (no consensus_at column in current schema)
                created = row.created_at
                if created:
                    try:
                        t = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                        age_min = int((now - t).total_seconds() / 60)
                    except (ValueError, TypeError):
                        age_min = 99999
                else:
                    age_min = 99999
                if age_min < _CONSENSUS_GRACE_MINUTES:
                    continue

            discussions_dao.close(
                conn, disc_id,
                consensus=row.consensus or "consensus",
                now=now_str,
            )
            closed += 1
            topic = (row.topic or "")[:60]
            _age_str = f"{age_min}m" if age_min is not None else "closed_at already set"
            print(f"discussion-auto-close: {disc_id} → closed ({_age_str}) — {topic}")

        conn.commit()
    except Exception as e:
        print(f"discussion-auto-close: error: {e}", file=sys.stderr)
    finally:
        conn.close()

    return closed


_STALE_INBOX_DELETE_AGE_HOURS = 1  # delete items marked stale after 1h (they've had time for review)


def _auto_delete_stale_inbox(project_dir: str) -> int:
    """Delete stale inbox items older than _STALE_INBOX_DELETE_AGE_HOURS.

    Stale items are dead data — they've been marked as terminal by previous
    cleanup passes and serve no further purpose in the inbox. Deleting them
    keeps the inbox lean and prevents drift between status counts and actual
    issues.

    Returns count of items deleted.
    """
    from datetime import datetime, timezone, timedelta
    from superharness.engine.db import get_connection, init_db

    try:
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=_STALE_INBOX_DELETE_AGE_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
            # Delete stale items where the last update was before the cutoff
            cursor = conn.execute(
                "DELETE FROM inbox WHERE status='stale' AND (failed_at IS NULL OR failed_at < ?)",
                (cutoff,),
            )
            deleted = cursor.rowcount or 0
            if deleted > 0:
                conn.commit()
                print(f"auto-delete-stale: removed {deleted} stale inbox item(s)")
            return deleted
        finally:
            conn.close()
    except Exception as e:
        print(f"auto-delete-stale: failed: {e}", file=sys.stderr)
        return 0


def _cancel_undispatchable_agents(project_dir: str) -> int:
    """Cancel pending inbox items for agents that have no dispatch script.

    Uses the adapter registry as the canonical source of valid agent names.
    Falls back to script-glob + hardcoded names if the registry is unavailable.
    Returns count of items canceled.
    """
    known_agents = set()
    try:
        from superharness.engine.adapter_registry import list_adapters
        known_agents.update(list_adapters())
    except Exception:
        pass
    if not known_agents:
        import glob as _glob
        scripts_dir = _find_scripts_dir()
        for script in _glob.glob(os.path.join(scripts_dir, "delegate-to-*.sh")):
            name = os.path.basename(script).replace("delegate-to-", "").replace(".sh", "")
            known_agents.add(name)
        known_agents.update(["claude-code", "codex-cli", "gemini-cli"])

    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            rows = conn.execute(
                "SELECT id, target_agent FROM inbox WHERE status='pending' AND target_agent NOT IN ({})".format(
                    ",".join(f"'{a}'" for a in known_agents)
                )
            ).fetchall()
            canceled = 0
            for row in rows:
                conn.execute("UPDATE inbox SET status='stale', failed_reason=? WHERE id=?",
                             (f"agent '{row[1]}' has no dispatch adapter", row[0]))
                canceled += 1
            if canceled > 0:
                conn.commit()
                agents = set(r[1] for r in rows)
                print(f"undispatchable-cleanup: canceled {canceled} item(s) for unknown agent(s): {agents}")
            return canceled
        finally:
            conn.close()
    except Exception as e:
        print(f"undispatchable-cleanup: failed: {e}", file=sys.stderr)
        return 0


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
    non_interactive: bool = True,  # default non-interactive for auto-mode
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
    if not os.access(harness_dir, os.W_OK):
        _abort(f"error: .superharness/ is not writable — check permissions: {harness_dir}")

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

    # Acquire SQLite singleton lease alongside filesystem lock
    _sqlite_singleton_acquire(project_dir)

    def _on_exit(signum: int = 0, frame: object = None) -> None:
        _sqlite_singleton_release(project_dir)
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
                _sqlite_singleton_release(project_dir)
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
    parser.add_argument("--non-interactive", action="store_true", default=True)
    parser.add_argument("--codex-bypass", action="store_true", default=False)
    parser.add_argument("--recover-timeout-minutes", default="20", dest="recover_timeout_minutes")
    parser.add_argument("--recover-action", default="stale")
    parser.add_argument("--launcher-timeout", default="0")
    parser.add_argument("--lock-stale-minutes", default="30")
    parser.add_argument("--foreground", "-f", action="store_true", default=False)
    parser.add_argument("--loop", action="store_true", default=False,
                        help="Run in a foreground loop (alias for --foreground)")
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

    if opts.target not in ("both", "claude-code", "codex-cli", "gemini-cli"):
        _abort("--to must be one of: both, claude-code, codex-cli, gemini-cli", 2)

    if opts.recover_action not in ("stale", "retry"):
        _abort("--recover-action must be one of: stale, retry", 2)

    recover_timeout_minutes = _parse_nonneg_int("--recover-timeout-minutes", opts.recover_timeout_minutes)
    launcher_timeout = _parse_nonneg_int("--launcher-timeout", opts.launcher_timeout)
    lock_stale_minutes = _parse_nonneg_int("--lock-stale-minutes", opts.lock_stale_minutes)
    interval = _parse_pos_int("--interval", opts.interval)

    rc = watch(
        project_dir=opts.project,
        target=opts.target,
        foreground=opts.foreground or opts.loop,
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

