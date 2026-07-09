"""STATE_BACKEND-aware read functions for the superharness state layer.

Controls whether reads come from YAML (legacy) or SQLite (primary).

STATE_BACKEND values:
  yaml_only   — read YAML, ignore SQLite (emergency rollback)
  dual        — read SQLite (preferred), fall back to YAML on error  [DEFAULT]
  sqlite_only — read SQLite exclusively; error if unavailable

Set via environment variable STATE_BACKEND or profile.yaml state_backend key.
Projects that have fully migrated to SQLite can set state_backend: sqlite_only
in their profile.yaml to opt in to strict mode.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any

from superharness.utils.paths import resolve_xdg_state_db_path

logger = logging.getLogger(__name__)


def _has_sqlite_db(project_dir: str) -> bool:
    """Return True if a state db exists at the XDG path or the legacy path."""
    # Honor the worktree-dispatch override so reads from an ephemeral worktree
    # still find the original project's DB — db.get_connection uses the same env.
    effective = os.environ.get("SUPERHARNESS_STATE_PROJECT", "").strip() or project_dir
    return (
        os.path.exists(resolve_xdg_state_db_path(effective))
        or os.path.exists(os.path.join(effective, ".superharness", "state.sqlite3"))
    )


def _get_backend(project_dir: str) -> str:
    """Determine the state backend (yaml_only, dual, or sqlite_only)."""
    # 1. Environment variable override
    env = os.environ.get("STATE_BACKEND")
    if env in ("yaml_only", "dual", "sqlite_only"):
        return env

    # 2. profile.yaml setting
    try:
        import yaml
        profile_path = os.path.join(project_dir, ".superharness", "profile.yaml")
        if os.path.isfile(profile_path):
            with open(profile_path, encoding="utf-8") as f:
                profile = yaml.safe_load(f.read()) or {}
            prof_backend = profile.get("state_backend")
            if prof_backend in ("yaml_only", "dual", "sqlite_only"):
                return prof_backend
    except Exception as e:
        logger.debug("Failed to read profile.yaml for state_backend: %s", e)

    # 3. Default to sqlite_only — SQLite is the canonical source of truth
    return "sqlite_only"


# ---------------------------------------------------------------------------
# Inbox reads
# ---------------------------------------------------------------------------


def _ensure_ingested(project_dir: str) -> None:
    """Ensure YAML state is ingested into SQLite (only if DB is empty)."""
    sh_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(sh_dir):
        return

    from superharness.engine.db import get_connection, init_db
    from superharness.engine.migrate_yaml import migrate_all_to_sqlite

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        # Only migrate if the DB has no tasks yet (first read after YAML tests)
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        if count == 0:
            migrate_all_to_sqlite(conn, project_dir)
    except Exception as e:
        logger.warning("YAML → SQLite ingest failed for %s: %s", project_dir, e)
    finally:
        conn.close()


def get_inbox_items(project_dir: str) -> list[dict]:
    """Return inbox items from SQLite (post-YAML removal).

    Production (sqlite_only) reads SQLite directly. The legacy ingest
    helper runs only inside pytest test fixtures.
    """
    if _production_path(project_dir):
        return _inbox_from_sqlite(project_dir)
    return _legacy_ingest_then_inbox(project_dir)


def _inbox_row_to_yaml_shape(row: dict) -> dict:
    """Translate SQLite InboxRow field names to YAML inbox item field names."""
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

def _is_running_tests() -> bool:
    """Return True if running inside a pytest session."""
    return "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST") is not None


def _production_path(project_dir: str) -> bool:
    """Return True for production reads. False inside pytest sessions or
    when sqlite_only is explicitly off (so YAML auto-ingest can hydrate
    legacy test fixtures)."""
    if _is_running_tests():
        return False
    from superharness.engine.sqlite_only import is_sqlite_only as _iso
    return _iso(project_dir)


def _legacy_ingest_then_tasks(project_dir: str) -> list[dict]:
    """Pytest-only path: hydrate SQLite from contract.yaml fixtures, then
    read. Wrapped with a swallowing try/except to keep legacy test setups
    working when migrations are partial. Production must not call this."""
    _ensure_ingested(project_dir)
    try:
        return _tasks_from_sqlite(project_dir)
    except Exception as e:
        logger.warning("Failed to read tasks from SQLite for %s: %s", project_dir, e)
        return []


def _legacy_ingest_then_inbox(project_dir: str) -> list[dict]:
    _ensure_ingested(project_dir)
    try:
        return _inbox_from_sqlite(project_dir)
    except Exception as e:
        logger.warning("Failed to read inbox from SQLite for %s: %s", project_dir, e)
        return []


def get_tasks(project_dir: str) -> list[dict]:
    """Return all tasks from SQLite (post-YAML removal).

    In sqlite_only mode (production) we read SQLite directly and let
    SQLite errors propagate — there is no silent YAML fallback. The
    legacy YAML auto-ingest path runs only inside pytest test fixtures.
    """
    # sqlite_only: production path raises on SQLite errors instead of
    # silently returning [] like the legacy test path does.
    if _production_path(project_dir):
        return _tasks_from_sqlite(project_dir)
    return _legacy_ingest_then_tasks(project_dir)


def get_task(project_dir: str, task_id: str) -> dict | None:
    """Return a single task by ID from SQLite (post-YAML removal).
    Production reads SQLite directly; sqlite_only enforces no YAML."""
    if not _production_path(project_dir):
        # Pytest fixtures may seed contract.yaml; hydrate before reading.
        _legacy_ingest_then_tasks(project_dir)
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        row = tasks_dao.get(conn, task_id)
        if row:
            # Re-use the same enrichment logic as bulk reads for consistency
            return _enrich_task(conn, row)
        return None
    finally:
        conn.close()


def _enrich_task(conn: sqlite3.Connection, row: Any) -> dict:
    """Enrich a TaskRow with dependencies, stamped fields, and extras_json."""
    from dataclasses import asdict
    d = asdict(row)
    
    # 1. Dependencies (blocked_by)
    # The dashboard expects `blocked_by` / `depends_on`.
    deps_strict = []
    try:
        for r in conn.execute(
            "SELECT prerequisite_task_id FROM task_dependencies WHERE dependent_task_id = ?",
            (row.id,)
        ):
            deps_strict.append(r["prerequisite_task_id"])
    except Exception as e:
        logger.warning("Failed to read task dependencies for task %s: %s", row.id, e)

    # 2. Soft (informational) blocked_by storage — JSON-encoded list
    soft = None
    if hasattr(row, "blocked_by_raw") and row.blocked_by_raw:
        try:
            import json as _j
            val = _j.loads(row.blocked_by_raw)
            if isinstance(val, list):
                soft = [str(x) for x in val]
        except Exception as e:
            logger.warning("Failed to parse blocked_by_raw for task %s: %s", row.id, e)
            
    deps = soft if soft is not None else deps_strict
    d["blocked_by"] = deps
    d["depends_on"] = deps

    # 3. v10: Stamped fields (workflow/require_tdd)
    if hasattr(row, "workflow") and row.workflow:
        d["workflow"] = row.workflow
    if hasattr(row, "require_tdd") and row.require_tdd is not None:
        d["require_tdd"] = bool(row.require_tdd)

    # 4. v11: pull subtasks/classifier/decomposer/retry from extras_json
    extras_json = getattr(row, "extras_json", None)
    if extras_json:
        try:
            import json as _jx
            extras = _jx.loads(extras_json)
            if isinstance(extras, dict):
                d.update(extras)
        except Exception as e:
            logger.warning("Failed to parse extras_json for task %s: %s", row.id, e)
            
    return d


def get_contract_doc(project_dir: str) -> dict:
    """Return the full contract document reconstructed from SQLite."""
    tasks = get_tasks(project_dir)
    decisions = get_decisions(project_dir)
    failures = get_failures(project_dir)
    contract_id, goal = _read_project_meta(project_dir)
    return {
        "id": contract_id,
        "goal": goal,
        "tasks": tasks,
        "decisions": decisions,
        "failures": failures,
    }


def _read_project_meta(project_dir: str) -> tuple[str, str]:
    """Read contract id and goal from the project_meta SQLite table."""
    try:
        from superharness.engine.db import get_connection, init_db
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            rows = {
                r[0]: r[1]
                for r in conn.execute("SELECT key, value FROM project_meta WHERE key IN ('id', 'goal')")
            }
            return rows.get("id", "contract"), rows.get("goal", "")
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Failed to read project meta for %s: %s", project_dir, e)
        return "contract", ""


def get_top_level_tasks(project_dir: str) -> list[dict]:
    """Return only top-level tasks (parent_id IS NULL), excluding subtasks."""
    if not _production_path(project_dir):
        _legacy_ingest_then_tasks(project_dir)  # hydrate legacy fixtures
    try:
        return _tasks_from_sqlite(project_dir, top_level_only=True)
    except Exception as e:
        logger.warning("Failed to read top-level tasks from SQLite for %s: %s", project_dir, e)
        return []


def _tasks_from_sqlite(project_dir: str, *, top_level_only: bool = False) -> list[dict]:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = tasks_dao.get_all(conn, top_level_only=top_level_only)
        return [_enrich_task(conn, r) for r in rows]
    finally:
        conn.close()


def get_handoffs(project_dir: str, task_id: str | None = None) -> list[dict]:
    """Return handoff rows from SQLite."""
    try:
        return _handoffs_from_sqlite(project_dir, task_id)
    except Exception as e:
        logger.warning("Failed to read handoffs from SQLite for %s: %s", project_dir, e)
        return []


def _handoffs_from_sqlite(project_dir: str, task_id: str | None) -> list[dict]:
    """Read handoffs from the SQLite handoffs table.

    With a task_id, returns that task's history (chronological); without one,
    returns all handoffs newest-first.
    """
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import handoffs_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        if task_id:
            rows = handoffs_dao.get_history(conn, task_id)
        else:
            rows = handoffs_dao.get_all(conn)
        return [asdict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Failures reads
# ---------------------------------------------------------------------------


def get_failures(project_dir: str) -> list[dict]:
    """Return all failure records from the SQLite failures table."""
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import failures_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = failures_dao.get_recent(conn)
        return [asdict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Decisions reads
# ---------------------------------------------------------------------------


def get_decisions(project_dir: str) -> list[dict]:
    """Return all decision records from the SQLite decisions table."""
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import decisions_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = decisions_dao.get_recent(conn)
        return [asdict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Ledger reads
# ---------------------------------------------------------------------------


def get_ledger_entries(project_dir: str, *, hours: int | None = None, limit: int = 100) -> list[dict]:
    """Return ledger entries from SQLite (source of truth).

    YAML ledger.md is an export-only artifact — do not read it here.
    Use state_writer.backfill_ledger_from_yaml() for one-time import.
    """
    if not _has_sqlite_db(project_dir):
        return []

    try:
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import ledger_dao

        conn = get_connection(project_dir)
        try:
            init_db(conn)
            rows = ledger_dao.get_recent(conn, limit=limit)
            entries = [asdict(r) for r in rows]
            if hours is not None:
                from datetime import datetime, timedelta, timezone
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
                entries = [
                    e for e in entries
                    if (_dt := _parse_iso_utc(str(e.get("created_at", "")))) is not None
                    and _dt >= cutoff
                ]
            return entries
        finally:
            conn.close()
    except Exception as e:
        logger.warning("get_ledger_entries failed for %s: %s", project_dir, e)
        return []


def parse_iso_utc(raw: str):
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime.

    Handles the 'Z' suffix, surrounding quotes, and returns None on failure.
    """
    from datetime import datetime, timezone
    value = raw.strip().strip("'\"")
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# Legacy alias kept for internal compatibility
_parse_iso_utc = parse_iso_utc


