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

import yaml

from superharness.engine.yaml_helpers import safe_load_normalized

import yaml

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


