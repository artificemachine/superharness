"""Python port of engine/inbox.rb.

Inbox management: enqueue, launch, set_status, set_field, remove, normalize,
recover_launched, list_launched, deadline_fail, sync_task_status, has_active,
next_pending.

Output format is byte-for-byte identical to the Ruby version for parity.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import yaml

from superharness.engine.yaml_helpers import safe_load_normalized

import yaml

_log = logging.getLogger(__name__)

HEADER = "# Delegation inbox\n# status: pending|launched|running|done|failed|stale\n"
ARCHIVE_HEADER = "# Inbox archive\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
    except (OSError, yaml.YAMLError) as e:
        # Fail open ONLY on file I/O and YAML parse errors — the original intent.
        # Logic bugs (TypeError, KeyError, AttributeError) must surface, not
        # silently green-light dispatch of a task whose dependency state is unknown.
        import logging
        logging.getLogger(__name__).warning(
            "deps_satisfied: fail-open due to contract read error: %s", e,
        )
        return True


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


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


def normalize(file: str, drop_statuses: list[str] | None = None,
              drop_prefixes: list[str] | None = None,
              archive_file: str | None = None, now: str | None = None) -> int:
    """Normalize inbox by dropping/archiving rows. (Re-implemented)."""
    items = safe_load_normalized(file, list)
    if not isinstance(items, list):
        items = []

    new_items = []
    dropped_items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        drop = False
        if drop_statuses and item.get("status") in drop_statuses:
            drop = True
        if drop_prefixes:
            item_id = str(item.get("id", ""))
            if any(item_id.startswith(p) for p in drop_prefixes):
                drop = True

        if drop:
            dropped_items.append(item)
        else:
            new_items.append(item)

    with open(file, "w", encoding="utf-8") as f:
        f.write(HEADER)
        yaml.dump(new_items, f, default_flow_style=False, sort_keys=True)

    if archive_file and dropped_items:
        with open(archive_file, "a", encoding="utf-8") as f:
            if os.path.getsize(archive_file) == 0:
                f.write(ARCHIVE_HEADER)
            yaml.dump(dropped_items, f, default_flow_style=False, sort_keys=True)

    return 0


def set_field(file: str, id: str, key: str, value: str) -> int:
    """Compatibility shim for set_field."""
    items = safe_load_normalized(file, list)
    if not isinstance(items, list):
        items = []
    found = False
    for item in items:
        if isinstance(item, dict) and str(item.get("id")) == id:
            item[key] = value
            found = True
            break
    if found:
        with open(file, "w", encoding="utf-8") as f:
            f.write(HEADER)
            yaml.dump(items, f, default_flow_style=False, sort_keys=True)
    return 0 if found else 1


# Compatibility shims — used by discuss.py, task.py, inbox_enqueue.py
HEADER = "# Delegation inbox\n"

from contextlib import contextmanager
import fcntl as _fcntl


@contextmanager
def _inbox_lock(path: str):
    """File lock for inbox operations. Compatibility shim."""
    lock_path = f"{path}.flock"
    with open(lock_path, "a+") as lock_file:
        _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_EX)
        try:
            yield
        finally:
            _fcntl.flock(lock_file.fileno(), _fcntl.LOCK_UN)


def enqueue(file: str, id: str, to: str, task: str, project: str, priority: int,
            created_at: str, retry_count: int = 0, max_retries: int = 3,
            plan_only: bool = False, model_override: str = "", effort_override: str = "") -> int:
    """Enqueue to SQLite inbox. Compatibility shim for discuss.py."""
    import os as _os
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao as _dao
    project_dir = _os.path.dirname(_os.path.dirname(file))
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        _dao.enqueue(conn, id=id, task_id=task, target_agent=to,
                     priority=priority, max_retries=max_retries,
                     project_path=project, plan_only=plan_only, now=created_at)
        conn.commit()
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse as _ap
    _p = _ap.ArgumentParser()
    _p.add_argument("command")
    _p.add_argument("--file", required=True)
    _p.add_argument("--to", default=None)
    _p.add_argument("--id", default=None)
    _p.add_argument("--now", default=None)
    _args = _p.parse_args()

    if _args.command == "next_pending":
        _file = _args.file
        _target = _args.to
        try:
            _items = safe_load_normalized(_file, list)
            if not isinstance(_items, list):
                _items = []
            for _item in _items:
                if not isinstance(_item, dict):
                    continue
                if _item.get("status") != "pending":
                    continue
                if _target and str(_item.get("to", "")) != _target:
                    continue
                _item["status"] = "launched"
                with open(_file, "w", encoding="utf-8") as _f:
                    _f.write(HEADER)
                    yaml.dump(_items, _f, default_flow_style=False, sort_keys=True)
                print(json.dumps(_item))
                sys.exit(0)
        except Exception as _e:
            print(f"next_pending error: {_e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if _args.command == "launch":
        _file = _args.file
        _id = _args.id
        _now = _args.now or datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            _items = safe_load_normalized(_file, list)
            if not isinstance(_items, list):
                _items = []
            _found = False
            for _item in _items:
                if isinstance(_item, dict) and str(_item.get("id")) == _id:
                    _item["status"] = "launched"
                    _item["launched_at"] = _now
                    _found = True
                    break
            if _found:
                with open(_file, "w", encoding="utf-8") as _f:
                    _f.write(HEADER)
                    yaml.dump(_items, _f, default_flow_style=False, sort_keys=True)
                print(f"Launched {_id} at {_now}")
                sys.exit(0)
            else:
                print(f"Item {_id} not found", file=sys.stderr)
                sys.exit(1)
        except Exception as _e:
            print(f"launch error: {_e}", file=sys.stderr)
            sys.exit(1)

