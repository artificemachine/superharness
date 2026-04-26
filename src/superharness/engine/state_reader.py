"""STATE_BACKEND-aware read functions for the superharness state layer.

Controls whether reads come from YAML (legacy) or SQLite (cutover).

STATE_BACKEND values:
  yaml_only   — read YAML, ignore SQLite (emergency rollback)
  dual        — read SQLite (preferred), fall back to YAML on error  [DEFAULT]
  sqlite_only — read SQLite exclusively; error if unavailable

Set via environment variable STATE_BACKEND or profile.yaml state_backend key.
"""
from __future__ import annotations

import os
from typing import Any


def _has_sqlite_db(project_dir: str) -> bool:
    return os.path.exists(os.path.join(project_dir, ".superharness", "state.sqlite3"))


def _get_backend(project_dir: str) -> str:
    env = os.environ.get("STATE_BACKEND", "").strip().lower()
    if env in ("yaml_only", "dual", "sqlite_only"):
        return env
    # Fall back to profile.yaml
    try:
        import yaml
        profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
        if os.path.exists(profile_path):
            with open(profile_path, encoding="utf-8") as f:
                profile = yaml.safe_load(f) or {}
            val = str(profile.get("state_backend", "")).strip().lower()
            if val in ("yaml_only", "dual", "sqlite_only"):
                return val
    except Exception:
        pass
    return "dual"


# ---------------------------------------------------------------------------
# Inbox reads
# ---------------------------------------------------------------------------

def get_inbox_items(project_dir: str) -> list[dict]:
    """Return inbox items. Source determined by STATE_BACKEND."""
    backend = _get_backend(project_dir)
    if backend == "yaml_only":
        return _inbox_from_yaml(project_dir)
    if not _has_sqlite_db(project_dir):
        if backend == "sqlite_only":
            raise RuntimeError(f"sqlite_only mode but no DB at {project_dir!r}")
        return _inbox_from_yaml(project_dir)
    try:
        items = _inbox_from_sqlite(project_dir)
        return items
    except Exception:
        if backend == "sqlite_only":
            raise
        return _inbox_from_yaml(project_dir)


def _inbox_from_yaml(project_dir: str) -> list[dict]:
    import yaml
    inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    if not os.path.exists(inbox_path):
        return []
    with open(inbox_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [i for i in (data or []) if isinstance(i, dict)]


def _inbox_row_to_yaml_shape(row: dict) -> dict:
    """Translate SQLite InboxRow field names to YAML inbox item field names.

    Caller must pass a plain dict (e.g. from dataclasses.asdict()), not a dataclass.
    """
    out = dict(row)
    out["task"] = out.pop("task_id", out.get("task", ""))
    out["to"] = out.pop("target_agent", out.get("to", ""))
    out["project"] = out.pop("project_path", out.get("project"))
    return out


def _inbox_from_sqlite(project_dir: str) -> list[dict]:
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = inbox_dao.get_all(conn)
        return [_inbox_row_to_yaml_shape(asdict(r)) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Contract / task reads
# ---------------------------------------------------------------------------

def get_tasks(project_dir: str) -> list[dict]:
    """Return all tasks. Source determined by STATE_BACKEND."""
    backend = _get_backend(project_dir)
    if backend == "yaml_only":
        return _tasks_from_yaml(project_dir)
    if not _has_sqlite_db(project_dir):
        if backend == "sqlite_only":
            raise RuntimeError(f"sqlite_only mode but no DB at {project_dir!r}")
        return _tasks_from_yaml(project_dir)
    try:
        return _tasks_from_sqlite(project_dir)
    except Exception:
        if backend == "sqlite_only":
            raise
        return _tasks_from_yaml(project_dir)


def get_contract_doc(project_dir: str) -> dict:
    """Return the full contract document. In sqlite_only mode, reconstructs from SQLite only."""
    backend = _get_backend(project_dir)
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    if backend == "yaml_only":
        return _contract_yaml(contract_path)
    if backend == "sqlite_only":
        tasks = _tasks_from_sqlite(project_dir)
        return {"tasks": tasks}
    if not _has_sqlite_db(project_dir):
        return _contract_yaml(contract_path)
    try:
        tasks = _tasks_from_sqlite(project_dir)
        doc = _contract_yaml(contract_path)
        doc["tasks"] = tasks
        return doc
    except Exception:
        return _contract_yaml(contract_path)


def get_top_level_tasks(project_dir: str) -> list[dict]:
    """Return only top-level tasks (parent_id IS NULL), excluding subtasks."""
    backend = _get_backend(project_dir)
    if backend == "yaml_only":
        return _tasks_from_yaml(project_dir)
    if not _has_sqlite_db(project_dir):
        if backend == "sqlite_only":
            raise RuntimeError(f"sqlite_only mode but no DB at {project_dir!r}")
        return _tasks_from_yaml(project_dir)
    try:
        return _tasks_from_sqlite(project_dir, top_level_only=True)
    except Exception:
        if backend == "sqlite_only":
            raise
        return _tasks_from_yaml(project_dir)


def _tasks_from_yaml(project_dir: str) -> list[dict]:
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    doc = _contract_yaml(contract_path)
    tasks = doc.get("tasks") or []
    return [t for t in tasks if isinstance(t, dict)]


def _tasks_from_sqlite(project_dir: str, *, top_level_only: bool = False) -> list[dict]:
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = tasks_dao.get_all(conn, top_level_only=top_level_only)
        return [asdict(r) for r in rows]
    finally:
        conn.close()


def _contract_yaml(path: str) -> dict:
    import yaml
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc if isinstance(doc, dict) else {}


# ---------------------------------------------------------------------------
# Handoff reads
# ---------------------------------------------------------------------------

def get_handoffs(project_dir: str, task_id: str | None = None) -> list[dict]:
    """Return handoff rows. Source determined by STATE_BACKEND."""
    backend = _get_backend(project_dir)
    if backend == "yaml_only":
        return _handoffs_from_yaml(project_dir, task_id)
    try:
        return _handoffs_from_sqlite(project_dir, task_id)
    except Exception:
        if backend == "sqlite_only":
            raise
        return _handoffs_from_yaml(project_dir, task_id)


def _handoffs_from_yaml(project_dir: str, task_id: str | None) -> list[dict]:
    import glob
    import yaml
    handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
    if not os.path.isdir(handoffs_dir):
        return []
    pattern = os.path.join(handoffs_dir, f"*{task_id}*.yaml" if task_id else "*.yaml")
    results: list[dict] = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                results.append(data)
            elif isinstance(data, list):
                results.extend(i for i in data if isinstance(i, dict))
        except Exception:
            continue
    return results


def _handoffs_from_sqlite(project_dir: str, task_id: str | None) -> list[dict]:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import handoffs_dao
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = handoffs_dao.get_history(conn, task_id=task_id)
        return [dict(r) for r in rows]
    finally:
        conn.close()
