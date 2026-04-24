"""Python port of engine/inbox.rb.

Inbox management: enqueue, launch, set_status, set_field, remove, normalize,
recover_launched, list_launched, deadline_fail, sync_task_status, has_active,
next_pending.

Output format is byte-for-byte identical to the Ruby version for parity.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

from superharness.engine.yaml_helpers import safe_load_normalized

import yaml

HEADER = "# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n"
ARCHIVE_HEADER = "# Inbox archive\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_items(path: str) -> list:
    items = safe_load_normalized(path, list)
    return items  # type: ignore[return-value]


def _write_items(path: str, items: list) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(HEADER)
            f.write(yaml.dump(items, default_flow_style=False, allow_unicode=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        tmp_path = None  # successfully replaced; don't unlink
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@contextmanager
def _inbox_lock(path: str) -> Iterator[None]:
    lock_path = f"{path}.flock"
    with open(lock_path, "a+") as lock_file:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                try:
                    lock_file.seek(0)
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                except (IOError, OSError):
                    pass
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _append_archive(archive_path: str, items: list, now: str) -> None:
    if not items:
        return
    if not os.path.exists(archive_path):
        with open(archive_path, "w") as f:
            f.write(ARCHIVE_HEADER)
    with open(archive_path, "a") as f:
        f.write("\n")
        f.write(f"# normalized_at: {now}\n")
        f.write(yaml.dump(items, default_flow_style=False, allow_unicode=True))


def _process_alive(pid_str: object) -> bool:
    try:
        pid = int(str(pid_str))
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # os.kill(pid, 0) maps to GenerateConsoleCtrlEvent(CTRL_C_EVENT, pid)
        # on Windows, which sends CTRL+C to the entire process group — never use it.
        # Use OpenProcess + GetExitCodeProcess instead.
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False  # process not found or no access → treat as dead
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


def _norm_priority(v: object) -> int:
    try:
        p = int(str(v))
    except (TypeError, ValueError):
        return 2
    if p < 1 or p > 3:
        return 2
    return p


def _strict_int(v: object, name: str) -> int:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        sys.exit(f"{name} must be an integer, got: {v}")


def _deps_satisfied(contract_file: str, task_id: str) -> bool:
    """Return True if all blocked_by dependencies for task_id are done.

    Reads contract_file to resolve dependency statuses. Returns True if:
    - contract_file doesn't exist or can't be read
    - task_id not found in contract
    - blocked_by is absent, None, or "none"
    - all listed dependency task IDs have status "done"

    Returns False only when at least one dependency exists and is not done.
    """
    if not os.path.exists(contract_file):
        return True
    try:
        from superharness.engine.yaml_helpers import safe_load
        doc = safe_load(contract_file, dict)
        tasks = doc.get("tasks") or []
        task = next(
            (t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id),
            None,
        )
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
        status_map = {
            str(t.get("id", "")): str(t.get("status", ""))
            for t in tasks
            if isinstance(t, dict)
        }
        return all(status_map.get(dep_id, "") in ("done", "archived") for dep_id in dep_ids)
    except Exception:
        return True  # Fail open: don't block dispatch on read errors


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def next_pending(file: str, target: str | None = None, contract_file: str | None = None) -> int:
    items = _load_items(file)
    best = None
    best_prio = None
    best_idx = None
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")) != "pending":
            continue
        if target and str(item.get("to", "")) != target:
            continue
        # Dependency-aware scheduling: skip items whose deps are not satisfied
        if contract_file:
            task_id = str(item.get("task", ""))
            if task_id and not _deps_satisfied(contract_file, task_id):
                continue
        prio = _norm_priority(item.get("priority", 2))
        if best is None or prio < best_prio or (prio == best_prio and idx < best_idx):
            best = item
            best_prio = prio
            best_idx = idx
    if best is None:
        return 0
    out = {
        "id": str(best.get("id", "")),
        "to": str(best.get("to", "")),
        "task": str(best.get("task", "")),
        "project": str(best.get("project", "")),
        "retry_count": int(best.get("retry_count", 0) or 0),
        "max_retries": int(best.get("max_retries", 3) or 3),
        "priority": best_prio,
        "plan_only": bool(best.get("plan_only", False)),
    }
    print(json.dumps(out, separators=(", ", ": ")))
    return 0


def claim(file: str, now: str, target: str | None = None, contract_file: str | None = None) -> int:
    """Atomically claim (checkout) the next eligible pending inbox item.

    Combines dependency-filtered next_pending + launch in a single lock hold,
    preventing double-dispatch under concurrent parallel agents.

    Prints JSON with claimed item on success (rc=0, non-empty stdout).
    Returns rc=0 with empty stdout when nothing is eligible.
    Returns rc=4 when retry limit is exhausted (item → failed).
    """
    with _inbox_lock(file):
        items = _load_items(file)
        best = None
        best_prio = None
        best_idx = None
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")) != "pending":
                continue
            if target and str(item.get("to", "")) != target:
                continue
            if contract_file:
                task_id = str(item.get("task", ""))
                if task_id and not _deps_satisfied(contract_file, task_id):
                    continue
            prio = _norm_priority(item.get("priority", 2))
            if best is None or prio < best_prio or (prio == best_prio and idx < best_idx):
                best = item
                best_prio = prio
                best_idx = idx

        if best is None:
            return 0  # Nothing eligible to claim

        item = items[best_idx]
        retry_count = int(item.get("retry_count", 0) or 0)
        max_retries = int(item.get("max_retries", 3) or 3)

        if retry_count >= max_retries:
            item["status"] = "failed"
            item["failed_at"] = now
            items[best_idx] = item
            _write_items(file, items)
            print(f"result=retry_exhausted retry_count={retry_count} max_retries={max_retries}")
            return 4

        item["retry_count"] = retry_count + 1
        item["status"] = "launched"
        item["launched_at"] = now
        items[best_idx] = item
        _write_items(file, items)

        prio = _norm_priority(item.get("priority", 2))
        out = {
            "id": str(item.get("id", "")),
            "to": str(item.get("to", "")),
            "task": str(item.get("task", "")),
            "project": str(item.get("project", "")),
            "retry_count": item["retry_count"],
            "max_retries": max_retries,
            "priority": prio,
            "plan_only": bool(item.get("plan_only", False)),
        }
        print(json.dumps(out, separators=(", ", ": ")))
        return 0


def enqueue(
    file: str,
    id: str,
    to: str,
    task: str,
    project: str,
    priority: int,
    created_at: str,
    retry_count: int = 0,
    max_retries: int = 3,
    plan_only: bool = False,
) -> int:
    items = _load_items(file)
    if any(isinstance(x, dict) and str(x.get("id", "")) == str(id) for x in items):
        print(f"result=duplicate_id id={id}")
        return 2
    # Block duplicate active entries for the same task ID.
    # A task can only have one active delegation in the inbox at a time,
    # regardless of which agent is assigned. This prevents race conditions.
    # Exception: discussion round tasks (`.../round-N`) legitimately need one
    # entry per participant, so match on (task, to) for those.
    is_discussion_round = "/round-" in str(task)
    existing = next(
        (x for x in items if isinstance(x, dict)
         and str(x.get("task", "")) == str(task)
         and (not is_discussion_round or str(x.get("to", "")) == str(to))
         and x.get("status") in ("pending", "launched", "running", "paused")),
        None,
    )
    if existing is not None:
        print(f"result=duplicate_task task={task} to={to} existing_id={existing['id']} status={existing.get('status')}")
        return 2
    norm_p = _norm_priority(priority)
    item: dict = {
        "id": str(id),
        "to": str(to),
        "task": str(task),
        "project": str(project),
        "status": "pending",
        "priority": norm_p,
        "retry_count": int(retry_count),
        "max_retries": int(max_retries),
        "created_at": str(created_at),
    }
    if plan_only:
        item["plan_only"] = True
    items.append(item)
    _write_items(file, items)
    print(f"result=enqueued id={id} priority={norm_p}")
    return 0


def launch(file: str, id: str, now: str) -> int:
    items = _load_items(file)
    idx = next((i for i, x in enumerate(items) if isinstance(x, dict) and str(x.get("id", "")) == str(id)), None)
    if idx is None:
        print("result=not_found")
        return 2
    item = items[idx]
    if str(item.get("status", "")) != "pending":
        print(f"result=status_mismatch status={item.get('status', '')}")
        return 3
    retry_count = int(item.get("retry_count", 0) or 0)
    max_retries = int(item.get("max_retries", 3) or 3)
    if retry_count >= max_retries:
        item["status"] = "failed"
        item["failed_at"] = now
        items[idx] = item
        _write_items(file, items)
        print(f"result=retry_exhausted retry_count={retry_count} max_retries={max_retries}")
        return 4
    item["retry_count"] = retry_count + 1
    item["status"] = "launched"
    item["launched_at"] = now
    for rk in ("pause_reason", "failed_reason", "stale_reason", "stopped_reason"):
        item.pop(rk, None)
    items[idx] = item
    _write_items(file, items)
    prio = _norm_priority(item.get("priority", 2))
    print(f"result=launched retry_count={item['retry_count']} max_retries={max_retries} priority={prio}")
    return 0


def set_status(file: str, id: str, from_: str, to: str, now: str, stamp_key: str | None = None) -> int:
    items = _load_items(file)
    idx = next((i for i, x in enumerate(items) if isinstance(x, dict) and str(x.get("id", "")) == str(id)), None)
    if idx is None:
        return 2
    item = items[idx]
    if str(item.get("status", "")) != str(from_):
        return 3
    item["status"] = to
    if stamp_key and stamp_key.strip():
        item[stamp_key] = now
    # Clear stale reason fields on forward transitions to active states
    if to in ("pending", "launched", "running"):
        for rk in ("pause_reason", "failed_reason", "stale_reason", "stopped_reason"):
            item.pop(rk, None)
    items[idx] = item
    _write_items(file, items)
    return 0


def set_field(file: str, id: str, key: str, value: str | None) -> int:
    items = _load_items(file)
    idx = next((i for i, x in enumerate(items) if isinstance(x, dict) and str(x.get("id", "")) == str(id)), None)
    if idx is None:
        return 2
    item = items[idx]
    if value is None or str(value).strip() == "":
        item.pop(key, None)
    else:
        item[key] = value
    items[idx] = item
    _write_items(file, items)
    return 0


def remove_item(file: str, id: str) -> int:
    items = _load_items(file)
    idx = next((i for i, x in enumerate(items) if isinstance(x, dict) and str(x.get("id", "")) == str(id)), None)
    if idx is None:
        print(f"result=not_found id={id}")
        return 2
    item = items[idx]
    del items[idx]
    _write_items(file, items)
    print(f"result=removed id={id} status={item.get('status', '')} task={item.get('task', '')} to={item.get('to', '')}")
    return 0


def _task_is_dispatch_ready(project_dir: str, task_id: str) -> bool:
    """Check if a contract task is in a dispatch-ready status."""
    contract_file = os.path.join(project_dir, ".superharness", "contract.yaml")
    if not os.path.exists(contract_file):
        return False
    try:
        from superharness.engine.yaml_helpers import safe_load
        doc = safe_load(contract_file, dict)
        tasks = doc.get("tasks") or []
        task = next((t for t in tasks if isinstance(t, dict) and str(t.get("id", "")) == task_id), None)
        if task is None:
            return False
        status = str(task.get("status", ""))
        return status in ("plan_approved", "in_progress", "todo")
    except Exception:
        return False


def normalize(
    file: str,
    drop_statuses: list[str],
    drop_prefixes: list[str],
    archive_file: str | None = None,
    now: str | None = None,
) -> int:
    items = _load_items(file)
    filtered = []
    dropped = []

    # Derive project dir from inbox file path
    project_dir = os.path.dirname(os.path.dirname(file))

    for item in items:
        if not isinstance(item, dict):
            filtered.append(item)
            continue
        id_ = str(item.get("id", ""))
        status = str(item.get("status", ""))
        task_id = str(item.get("task", ""))
        drop_by_status = status in drop_statuses
        drop_by_prefix = any(p and id_.startswith(p) for p in drop_prefixes)
        if drop_by_status or drop_by_prefix:
            # Re-enqueue as pending if contract task is still dispatch-ready
            if drop_by_status and task_id and _task_is_dispatch_ready(project_dir, task_id):
                item["status"] = "pending"
                item.pop("failed_at", None)
                item.pop("launched_at", None)
                item["retry_count"] = 0
                filtered.append(item)
                print(f"normalize: re-enqueued {task_id} (contract still dispatch-ready)")
            else:
                dropped.append(item)
        else:
            filtered.append(item)
    _write_items(file, filtered)
    if archive_file:
        ts = now or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        _append_archive(archive_file, dropped, ts)
    return 0


def recover_launched(file: str, now: str, timeout_minutes: int, action: str) -> int:
    try:
        now_time = datetime.fromisoformat(now.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"recover_launched: invalid --now timestamp: {now}")
    timeout_seconds = int(timeout_minutes) * 60
    updated = False
    stale_count = 0
    retried_count = 0
    failed_count = 0

    # Hold the flock for the entire read-modify-write cycle so a concurrent
    # dispatcher's claim() cannot clobber our stale-recovery writes.
    with _inbox_lock(file):
        items = _load_items(file)

        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            if str(item.get("status", "")) != "launched":
                continue
            if _process_alive(item.get("pid")):
                continue
            launched_at = str(item.get("launched_at", ""))
            if not launched_at:
                continue
            try:
                launched_time = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
            except ValueError:
                item["status"] = "stale"
                item["stale_at"] = now
                item["stale_reason"] = "invalid_launched_at"
                item.pop("pid", None)
                item.pop("launched_at", None)
                items[idx] = item
                stale_count += 1
                updated = True
                continue

            elapsed = (now_time - launched_time).total_seconds()
            if elapsed < timeout_seconds:
                continue

            if action == "retry":
                retry_count = int(item.get("retry_count", 0) or 0)
                max_retries = int(item.get("max_retries", 3) or 3)
                if retry_count >= max_retries:
                    item["status"] = "failed"
                    item["failed_at"] = now
                    item["failed_reason"] = "stale_timeout_exhausted"
                    failed_count += 1
                else:
                    item["status"] = "pending"
                    item["stale_at"] = now
                    item["stale_reason"] = "stale_timeout_retry"
                    retried_count += 1
            else:
                item["status"] = "stale"
                item["stale_at"] = now
                item["stale_reason"] = "stale_timeout"
                stale_count += 1

            item.pop("launched_at", None)
            item.pop("pid", None)
            items[idx] = item
            updated = True

        if updated:
            _write_items(file, items)

    print(f"result=ok updated={1 if updated else 0} stale={stale_count} retried={retried_count} failed={failed_count}")
    return 0


def list_launched(file: str) -> int:
    items = _load_items(file)
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")) != "launched":
            continue
        result.append(
            {
                "id": str(item.get("id", "")),
                "to": str(item.get("to", "")),
                "task": str(item.get("task", "")),
                "project": str(item.get("project", "")),
                "launched_at": str(item.get("launched_at", "") or ""),
                "priority": _norm_priority(item.get("priority", 2)),
                "retry_count": int(item.get("retry_count", 0) or 0),
                "max_retries": int(item.get("max_retries", 3) or 3),
            }
        )
    print(json.dumps(result, separators=(", ", ": ")))
    return 0


def deadline_fail(file: str, id: str, now: str, reason: str = "") -> int:
    items = _load_items(file)
    idx = next((i for i, x in enumerate(items) if isinstance(x, dict) and str(x.get("id", "")) == str(id)), None)
    if idx is None:
        print("result=not_found")
        return 2
    item = items[idx]
    if str(item.get("status", "")) != "launched":
        print(f"result=status_mismatch status={item.get('status', '')}")
        return 3
    item["status"] = "failed"
    item["failed_at"] = now
    item["failed_reason"] = reason.strip() if reason.strip() else "deadline_exceeded"
    item.pop("launched_at", None)
    items[idx] = item
    _write_items(file, items)
    print(f"result=ok id={id} task={item.get('task', '')} to={item.get('to', '')} project={item.get('project', '')}")
    return 0


def sync_task_status(file: str, task: str, to: str, now: str) -> int:
    items = _load_items(file)
    active_statuses = {"pending", "launched", "running", "failed", "paused", "stale"}
    updated = 0
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if str(item.get("task", "")) != str(task):
            continue
        if str(item.get("status", "")) not in active_statuses:
            continue
        item["status"] = to
        stamp = {"done": "done_at", "failed": "failed_at", "stopped": "stopped_at"}.get(to)
        if stamp:
            item[stamp] = now
        item.pop("launched_at", None)
        item.pop("running_at", None)
        item.pop("pid", None)
        items[idx] = item
        updated += 1
    if updated > 0:
        _write_items(file, items)
    print(f"result=ok synced={updated}")
    return 0


def has_active(file: str, to: str, task: str) -> int:
    items = _load_items(file)
    active_statuses = {"pending", "paused", "launched", "running"}
    active = any(
        isinstance(item, dict)
        and str(item.get("task", "")) == str(task)
        and str(item.get("to", "")) == str(to)
        and str(item.get("status", "")) in active_statuses
        for item in items
    )
    print("true" if active else "false")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(
            "Usage: inbox <next_pending|launch|enqueue|set_status|set_field|remove"
            "|sync_task_status|normalize|recover_launched|list_launched|deadline_fail|has_active> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = argv[0]
    rest = argv[1:]

    valid_cmds = {
        "next_pending", "launch", "enqueue", "set_status", "set_field",
        "remove", "sync_task_status", "normalize", "recover_launched",
        "list_launched", "deadline_fail", "has_active", "claim",
    }
    if cmd not in valid_cmds:
        print(
            "Usage: inbox <next_pending|launch|enqueue|set_status|set_field|remove"
            "|sync_task_status|normalize|recover_launched|list_launched|deadline_fail|has_active|claim> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(add_help=False)

    if cmd == "next_pending":
        parser.add_argument("--file")
        parser.add_argument("--to")
        parser.add_argument("--contract")
        opts = parser.parse_args(rest)
        if not opts.file:
            print("--file is required", file=sys.stderr)
            sys.exit(1)
        rc = next_pending(opts.file, target=opts.to or None, contract_file=opts.contract or None)
        sys.exit(rc)

    elif cmd == "claim":
        parser.add_argument("--file")
        parser.add_argument("--now")
        parser.add_argument("--to")
        parser.add_argument("--contract")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.now]):
            print("--file and --now are required", file=sys.stderr)
            sys.exit(1)
        rc = claim(opts.file, opts.now, target=opts.to or None, contract_file=opts.contract or None)
        sys.exit(rc)

    elif cmd == "enqueue":
        parser.add_argument("--file")
        parser.add_argument("--id")
        parser.add_argument("--to")
        parser.add_argument("--task")
        parser.add_argument("--project")
        parser.add_argument("--priority")
        parser.add_argument("--created-at", dest="created_at")
        parser.add_argument("--retry-count", dest="retry_count")
        parser.add_argument("--max-retries", dest="max_retries")
        parser.add_argument("--plan-only", action="store_true", default=False)
        opts = parser.parse_args(rest)
        required = ["file", "id", "to", "task", "project", "priority", "created_at"]
        if not all(getattr(opts, k, None) for k in required):
            print("--file, --id, --to, --task, --project, --priority, --created-at are required", file=sys.stderr)
            sys.exit(1)
        prio = _strict_int(opts.priority, "--priority")
        rc_val = opts.retry_count
        mr_val = opts.max_retries
        retry_count = _strict_int(rc_val, "--retry-count") if rc_val is not None else 0
        max_retries = _strict_int(mr_val, "--max-retries") if mr_val is not None else 3
        with _inbox_lock(opts.file):
            rc = enqueue(
                opts.file, opts.id, opts.to, opts.task, opts.project,
                prio, opts.created_at, retry_count, max_retries,
                plan_only=opts.plan_only,
            )
        sys.exit(rc)

    elif cmd == "launch":
        parser.add_argument("--file")
        parser.add_argument("--id")
        parser.add_argument("--now")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.id, opts.now]):
            print("--file, --id, --now are required", file=sys.stderr)
            sys.exit(1)
        with _inbox_lock(opts.file):
            rc = launch(opts.file, opts.id, opts.now)
        sys.exit(rc)

    elif cmd == "set_status":
        parser.add_argument("--file")
        parser.add_argument("--id")
        parser.add_argument("--from", dest="from_")
        parser.add_argument("--to")
        parser.add_argument("--now")
        parser.add_argument("--stamp-key", dest="stamp_key")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.id, opts.from_, opts.to, opts.now]):
            print("--file, --id, --from, --to, --now are required", file=sys.stderr)
            sys.exit(1)
        with _inbox_lock(opts.file):
            rc = set_status(opts.file, opts.id, opts.from_, opts.to, opts.now, stamp_key=opts.stamp_key)
        sys.exit(rc)

    elif cmd == "set_field":
        parser.add_argument("--file")
        parser.add_argument("--id")
        parser.add_argument("--key")
        parser.add_argument("--value")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.id, opts.key]):
            print("--file, --id, --key are required", file=sys.stderr)
            sys.exit(1)
        with _inbox_lock(opts.file):
            rc = set_field(opts.file, opts.id, opts.key, opts.value)
        sys.exit(rc)

    elif cmd == "remove":
        parser.add_argument("--file")
        parser.add_argument("--id")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.id]):
            print("--file and --id are required", file=sys.stderr)
            sys.exit(1)
        with _inbox_lock(opts.file):
            rc = remove_item(opts.file, opts.id)
        sys.exit(rc)

    elif cmd == "normalize":
        parser.add_argument("--file")
        parser.add_argument("--drop-status", dest="drop_statuses", action="append", default=[])
        parser.add_argument("--drop-prefix", dest="drop_prefixes", action="append", default=[])
        parser.add_argument("--archive-file", dest="archive_file")
        parser.add_argument("--now")
        opts = parser.parse_args(rest)
        if not opts.file:
            print("--file is required", file=sys.stderr)
            sys.exit(1)
        ds = opts.drop_statuses or ["stale"]
        with _inbox_lock(opts.file):
            rc = normalize(opts.file, ds, opts.drop_prefixes or [], archive_file=opts.archive_file, now=opts.now)
        sys.exit(rc)

    elif cmd == "recover_launched":
        parser.add_argument("--file")
        parser.add_argument("--now")
        parser.add_argument("--timeout-minutes", dest="timeout_minutes", default="20")
        parser.add_argument("--action", default="stale")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.now]):
            print("--file and --now are required", file=sys.stderr)
            sys.exit(1)
        if opts.action not in ("stale", "retry"):
            print("--action must be stale or retry", file=sys.stderr)
            sys.exit(1)
        tm = _strict_int(opts.timeout_minutes, "--timeout-minutes")
        rc = recover_launched(opts.file, opts.now, tm, opts.action)
        sys.exit(rc)

    elif cmd == "list_launched":
        parser.add_argument("--file")
        opts = parser.parse_args(rest)
        if not opts.file:
            print("--file is required", file=sys.stderr)
            sys.exit(1)
        rc = list_launched(opts.file)
        sys.exit(rc)

    elif cmd == "deadline_fail":
        parser.add_argument("--file")
        parser.add_argument("--id")
        parser.add_argument("--now")
        parser.add_argument("--reason", default="deadline_exceeded")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.id, opts.now]):
            print("--file, --id, --now are required", file=sys.stderr)
            sys.exit(1)
        with _inbox_lock(opts.file):
            rc = deadline_fail(opts.file, opts.id, opts.now, opts.reason or "")
        sys.exit(rc)

    elif cmd == "sync_task_status":
        parser.add_argument("--file")
        parser.add_argument("--task")
        parser.add_argument("--to")
        parser.add_argument("--now")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.task, opts.to, opts.now]):
            print("--file, --task, --to, --now are required", file=sys.stderr)
            sys.exit(1)
        with _inbox_lock(opts.file):
            rc = sync_task_status(opts.file, opts.task, opts.to, opts.now)
        sys.exit(rc)

    elif cmd == "has_active":
        parser.add_argument("--file")
        parser.add_argument("--to")
        parser.add_argument("--task")
        opts = parser.parse_args(rest)
        if not all([opts.file, opts.to, opts.task]):
            print("--file, --to, --task are required", file=sys.stderr)
            sys.exit(1)
        rc = has_active(opts.file, opts.to, opts.task)
        sys.exit(rc)


if __name__ == "__main__":
    main()
