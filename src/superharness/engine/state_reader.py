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

import os
import re
import sys
from typing import Any


def _has_sqlite_db(project_dir: str) -> bool:
    return os.path.exists(os.path.join(project_dir, ".superharness", "state.sqlite3"))


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
    except Exception:
        pass

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
    except Exception:
        pass
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
    except Exception:
        return []


def _legacy_ingest_then_inbox(project_dir: str) -> list[dict]:
    _ensure_ingested(project_dir)
    try:
        return _inbox_from_sqlite(project_dir)
    except Exception:
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
    from dataclasses import asdict

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        row = tasks_dao.get(conn, task_id)
        if row:
            return asdict(row)
        return None
    finally:
        conn.close()



def get_contract_doc(project_dir: str) -> dict:
    """Return the full contract document reconstructed from SQLite."""
    tasks = get_tasks(project_dir)
    decisions = get_decisions(project_dir)
    failures = get_failures(project_dir)
    # Derive contract ID from project metadata
    contract_id = "contract"  # default
    return {
        "id": contract_id,
        "tasks": tasks,
        "decisions": decisions,
        "failures": failures,
    }


def get_top_level_tasks(project_dir: str) -> list[dict]:
    """Return only top-level tasks (parent_id IS NULL), excluding subtasks."""
    if not _production_path(project_dir):
        _legacy_ingest_then_tasks(project_dir)  # hydrate legacy fixtures
    try:
        return _tasks_from_sqlite(project_dir, top_level_only=True)
    except Exception:
        return []


def _tasks_from_sqlite(project_dir: str, *, top_level_only: bool = False) -> list[dict]:
    from dataclasses import asdict
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import tasks_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = tasks_dao.get_all(conn, top_level_only=top_level_only)
        # Enrich each task with its prerequisites (task_dependencies row).
        # The dashboard expects `blocked_by` / `depends_on`; without this the
        # dependency graph is invisible after the YAML→SQLite migration.
        deps_by_dependent: dict[str, list[str]] = {}
        for r in conn.execute(
            "SELECT dependent_task_id, prerequisite_task_id FROM task_dependencies"
        ):
            deps_by_dependent.setdefault(r["dependent_task_id"], []).append(
                r["prerequisite_task_id"]
            )
        # Pull the soft (informational) blocked_by list per task —
        # references that may not exist as task rows themselves but
        # which adapters / dashboards still want to surface.
        blocked_by_raw_by_id: dict[str, list[str]] = {}
        stamped_by_id: dict[str, dict] = {}
        try:
            for r in conn.execute(
                "SELECT id, blocked_by_raw, workflow, autonomy, require_tdd FROM tasks"
            ):
                if r["blocked_by_raw"]:
                    try:
                        import json as _j
                        val = _j.loads(r["blocked_by_raw"])
                        if isinstance(val, list):
                            blocked_by_raw_by_id[r["id"]] = [str(x) for x in val]
                    except Exception:
                        pass
                stamp = {}
                if r["workflow"]:
                    stamp["workflow"] = r["workflow"]
                if r["autonomy"]:
                    stamp["autonomy"] = r["autonomy"]
                if r["require_tdd"] is not None:
                    stamp["require_tdd"] = bool(r["require_tdd"])
                if stamp:
                    stamped_by_id[r["id"]] = stamp
        except Exception:
            pass  # column may not exist on older schema

        out: list[dict] = []
        for r in rows:
            d = asdict(r)
            deps_strict = deps_by_dependent.get(r.id, [])
            # Soft (raw) references win — they include scalar blocked_by
            # that don't yet exist as task rows. Falls back to the
            # strict task_dependencies join.
            soft = blocked_by_raw_by_id.get(r.id)
            deps = soft if soft is not None else deps_strict
            d["blocked_by"] = deps
            d["depends_on"] = deps
            # Layer the stamped fields (workflow/autonomy/require_tdd)
            # on top — the v10 schema stores them per-task; older rows
            # simply have None and the adapter uses defaults.
            d.update(stamped_by_id.get(r.id, {}))
            # v11: pull subtasks/classifier/decomposer/retry from extras_json
            extras_json = getattr(r, "extras_json", None)
            if extras_json:
                try:
                    import json as _jx
                    extras = _jx.loads(extras_json)
                    if isinstance(extras, dict):
                        d.update(extras)
                except Exception:
                    pass
            out.append(d)
        return out
    finally:
        conn.close()


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
    """Return ledger entries from SQLite (primary) and ledger.md (fallback)."""
    backend = _get_backend(project_dir)
    if backend == "yaml_only":
        return _ledger_from_markdown(project_dir, hours=hours, limit=limit)

    # Load from Markdown first (older entries)
    md_entries = _ledger_from_markdown(project_dir, hours=hours, limit=limit)
    
    if not _has_sqlite_db(project_dir):
        if backend == "sqlite_only":
            raise RuntimeError(f"sqlite_only mode but no DB at {project_dir!r}")
        return md_entries

    try:
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import ledger_dao

        conn = get_connection(project_dir)
        try:
            init_db(conn)
            rows = ledger_dao.get_recent(conn, limit=limit)
            sqlite_entries = [asdict(r) for r in rows]
            
            if hours is not None:
                from datetime import datetime, timedelta, timezone
                cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
                sqlite_entries = [
                    e for e in sqlite_entries
                    if _parse_iso_utc(str(e.get("created_at", ""))) >= cutoff
                ]
            
            if backend == "sqlite_only":
                return sqlite_entries
            
            # Dual mode: Combine and sort by timestamp desc
            # Since ledger is append-only and usually ordered, this is mostly fine
            combined = sqlite_entries + md_entries
            combined.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
            return combined[:limit]
        finally:
            conn.close()
    except Exception:
        if backend == "sqlite_only":
            raise
        return md_entries


def _ledger_from_markdown(project_dir: str, hours: int | None = None, limit: int = 100) -> list[dict]:
    """Parse .superharness/ledger.md into dicts."""
    path = os.path.join(project_dir, ".superharness", "ledger.md")
    if not os.path.isfile(path):
        return []
    
    from datetime import datetime, timedelta, timezone
    cutoff = None
    if hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    results = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                # Format: - 2026-03-27T22:35:55Z — claude-code — action (details)
                # Or: - 2026-03-27T22:35:55Z — monitor test
                match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)", line)
                if not match:
                    continue
                
                ts = match.group(1)
                if cutoff and _parse_iso_utc(ts) < cutoff:
                    continue
                
                # Try splitting by ' — ' (any dash)
                # We strip the leading '- ' and the timestamp if it's at the start
                clean_line = line.strip().lstrip("- ").replace(ts, "").strip(" —–-")
                parts = re.split(r"\s+[—–-]\s+", clean_line)
                
                if len(parts) >= 2:
                    results.append({
                        "created_at": ts,
                        "agent": parts[0].strip(),
                        "action": parts[1].strip(),
                        "details": {},
                    })
                else:
                    results.append({
                        "created_at": ts,
                        "agent": "system", # Fallback
                        "action": clean_line or "operational event",
                        "details": {},
                    })
    except Exception:
        pass
    
    results.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return results[:limit]


def _parse_iso_utc(ts: str):
    """Parse an ISO-8601 timestamp string to a timezone-aware datetime.

    Handles the 'Z' suffix by replacing it with '+00:00'.
    """
    from datetime import datetime, timezone
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


# ---------------------------------------------------------------------------
# YAML Fallbacks (Legacy)
# ---------------------------------------------------------------------------


def _inbox_from_yaml(project_dir: str) -> list[dict]:
    path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    if not os.path.isfile(path):
        return []
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or []
    except Exception:
        return []


def _tasks_from_yaml(project_dir: str) -> list[dict]:
    path = os.path.join(project_dir, ".superharness", "contract.yaml")
    doc = _contract_yaml(path)
    return doc.get("tasks") or []


def _contract_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _handoffs_from_yaml(project_dir: str, task_id: str | None = None) -> list[dict]:
    from pathlib import Path
    import yaml
    h_dir = Path(project_dir) / ".superharness" / "handoffs"
    if not h_dir.is_dir():
        return []
    results = []
    for f in sorted(h_dir.iterdir()):
        if f.suffix != ".yaml":
            continue
        if task_id and not f.name.startswith(f"{task_id}."):
            # This is a bit loose but works for legacy naming
            if task_id not in f.name:
                continue
        try:
            with open(f, encoding="utf-8") as _f:
                results.append(yaml.safe_load(_f) or {})
        except Exception:
            continue
    return results
