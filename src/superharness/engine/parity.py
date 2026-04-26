from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
from dataclasses import dataclass, field

import yaml

from superharness.engine.state_errors import StateError
from superharness.engine import yaml_sync

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TableDrift:
    table: str
    only_in_db: int
    only_in_yaml: int
    mismatched: int


@dataclass(frozen=True)
class ParityReport:
    checked_at: str
    healthy: bool
    drifts: list[TableDrift]
    yaml_sync_lag: int
    foreign_key_violations: int = 0


def check_parity(
    conn: sqlite3.Connection,
    project_dir: str,
) -> ParityReport:
    """Compare SQLite rows against YAML files. Returns full report without mutating state."""
    from superharness.engine.db import now_iso

    checked_at = now_iso()
    drifts: list[TableDrift] = []

    drifts.append(_check_tasks(conn, project_dir))
    drifts.append(_check_inbox(conn, project_dir))
    drifts.append(_check_handoffs(conn, project_dir))
    drifts.append(_check_failures(conn, project_dir))
    drifts.append(_check_decisions(conn, project_dir))

    try:
        lag = conn.execute(
            "SELECT COUNT(*) FROM yaml_sync_queue WHERE status='pending'"
        ).fetchone()[0]
    except sqlite3.Error as exc:
        logger.warning("parity: could not read yaml_sync_queue: %s", exc)
        lag = -1

    fk_violations = _check_foreign_keys(conn)

    healthy = (
        all(
            d.only_in_db == 0 and d.only_in_yaml == 0 and d.mismatched == 0
            for d in drifts
        )
        and fk_violations == 0
    )
    return ParityReport(
        checked_at=checked_at,
        healthy=healthy,
        drifts=drifts,
        yaml_sync_lag=lag,
        foreign_key_violations=fk_violations,
    )


def heal_parity(
    conn: sqlite3.Connection,
    project_dir: str,
    report: ParityReport,
) -> int:
    """Re-enqueue sync ops for drifted rows found only in DB; upserts to SQLite for only_in_yaml.

    Returns count of ops enqueued or rows upserted.
    """
    from superharness.engine.db import now_iso

    enqueued = 0
    now = now_iso()

    for drift in report.drifts:
        if drift.table == "tasks":
            if drift.only_in_db > 0:
                enqueued += _heal_tasks_db_to_yaml(conn, project_dir, now)
            if drift.only_in_yaml > 0:
                enqueued += _heal_tasks_yaml_to_db(conn, project_dir, now)
            if drift.mismatched > 0:
                enqueued += _heal_tasks_mismatched(conn, project_dir, now)
        elif drift.table == "inbox":
            if drift.only_in_db > 0:
                enqueued += _heal_inbox(conn, project_dir, now)
            if drift.only_in_yaml > 0:
                enqueued += _heal_inbox_yaml_to_db(conn, project_dir, now)
        elif drift.table == "handoffs":
            if drift.only_in_yaml > 0:
                enqueued += _heal_handoffs_yaml_to_db(conn, project_dir, now)
        elif drift.table == "failures":
            if drift.only_in_yaml > 0:
                enqueued += _heal_failures_yaml_to_db(conn, project_dir, now)

    return enqueued


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _stable_hash(*parts: object) -> str:
    raw = "|".join(str(p) if p is not None else "" for p in parts)
    return hashlib.md5(raw.encode()).hexdigest()


def _load_yaml_list(path: str, *, include_subtasks: bool = False) -> list[dict]:
    """Load a YAML list from path. With include_subtasks=True also flattens nested subtasks."""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if isinstance(data, list):
        items = [item for item in data if isinstance(item, dict)]
    elif isinstance(data, dict) and "tasks" in data:
        tasks = data["tasks"]
        items = [t for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []
    else:
        return []

    if not include_subtasks:
        return items

    result: list[dict] = []
    for item in items:
        result.append(item)
        for st in item.get("subtasks") or []:
            if isinstance(st, dict):
                result.append(st)
    return result


def _check_tasks(conn: sqlite3.Connection, project_dir: str) -> TableDrift:
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    # include_subtasks=True so orchestrator-nested subtasks are visible to parity (B2)
    yaml_map = {
        t["id"]: t for t in _load_yaml_list(contract_path, include_subtasks=True) if "id" in t
    }

    try:
        db_rows = conn.execute(
            "SELECT id, status, owner, title FROM tasks"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("parity tasks: db read failed: %s", exc)
        db_rows = []

    db_map = {r["id"]: r for r in db_rows}
    only_db = len(set(db_map) - set(yaml_map))
    only_yaml = len(set(yaml_map) - set(db_map))

    mismatched = 0
    for tid in set(db_map) & set(yaml_map):
        db_r = db_map[tid]
        y = yaml_map[tid]
        # Normalize: YAML status=None is semantically equivalent to "todo"
        db_status = str(db_r["status"] or "todo")
        y_status = str(y.get("status") or "todo")
        db_sig = _stable_hash(db_status, db_r["owner"], db_r["title"])
        y_sig = _stable_hash(y_status, y.get("owner"), y.get("title"))
        if db_sig != y_sig:
            mismatched += 1

    return TableDrift(table="tasks", only_in_db=only_db, only_in_yaml=only_yaml, mismatched=mismatched)


_INBOX_ACTIVE_STATUSES = ("pending", "launched", "running", "paused")


def _check_inbox(conn: sqlite3.Connection, project_dir: str) -> TableDrift:
    inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    yaml_map = {i["id"]: i for i in _load_yaml_list(inbox_path) if "id" in i}

    try:
        # Only compare active rows — failed/stopped/done are archived out of
        # inbox.yaml by design and must not count as drift.
        placeholders = ",".join("?" * len(_INBOX_ACTIVE_STATUSES))
        db_rows = conn.execute(
            f"SELECT id, status, target_agent, task_id FROM inbox WHERE status IN ({placeholders})",
            _INBOX_ACTIVE_STATUSES,
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("parity inbox: db read failed: %s", exc)
        db_rows = []

    db_map = {r["id"]: r for r in db_rows}
    only_db = len(set(db_map) - set(yaml_map))
    only_yaml = len(set(yaml_map) - set(db_map))

    mismatched = 0
    for iid in set(db_map) & set(yaml_map):
        db_r = db_map[iid]
        y = yaml_map[iid]
        db_sig = _stable_hash(db_r["status"], db_r["target_agent"], db_r["task_id"])
        y_sig = _stable_hash(y.get("status"), y.get("target_agent") or y.get("agent") or y.get("to"), y.get("task_id") or y.get("task"))
        if db_sig != y_sig:
            mismatched += 1

    return TableDrift(table="inbox", only_in_db=only_db, only_in_yaml=only_yaml, mismatched=mismatched)


def _check_handoffs(conn: sqlite3.Connection, project_dir: str) -> TableDrift:
    """Compare handoff files in .superharness/handoffs/ against SQLite handoffs rows.

    Only considers YAML entries whose task_id exists in the tasks table — handoffs
    referencing archived/deleted tasks are expected to be YAML-only and are excluded
    from the drift count to avoid permanent false positives.
    """
    handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")

    try:
        known_task_ids = {r[0] for r in conn.execute("SELECT id FROM tasks").fetchall()}
    except sqlite3.Error:
        known_task_ids = set()

    yaml_keys: set[tuple[str, str]] = set()
    if os.path.isdir(handoffs_dir):
        for fname in os.listdir(handoffs_dir):
            if not fname.endswith(".yaml"):
                continue
            fpath = os.path.join(handoffs_dir, fname)
            try:
                with open(fpath, encoding="utf-8") as f:
                    h = yaml.safe_load(f)
                if isinstance(h, dict):
                    task_id = str(h.get("task_id") or h.get("task") or "")
                    date = str(h.get("date") or "")
                    if task_id and task_id in known_task_ids:
                        yaml_keys.add((task_id, date))
            except Exception as exc:
                logger.debug("parity handoffs: could not parse %s: %s", fname, exc)

    try:
        # Only consider DB entries for tasks that currently exist — orphaned handoffs
        # (whose tasks were archived) are expected and excluded from drift counting.
        db_keys = {
            (r[0], r[1])
            for r in conn.execute("SELECT task_id, created_at FROM handoffs").fetchall()
            if r[0] in known_task_ids
        }
    except sqlite3.Error as exc:
        logger.warning("parity handoffs: db read failed: %s", exc)
        db_keys = set()

    only_db = len(db_keys - yaml_keys)
    only_yaml = len(yaml_keys - db_keys)
    return TableDrift(table="handoffs", only_in_db=only_db, only_in_yaml=only_yaml, mismatched=0)


def _check_failures(conn: sqlite3.Connection, project_dir: str) -> TableDrift:
    """Compare failures.yaml entries against SQLite failures rows."""
    failures_path = os.path.join(project_dir, ".superharness", "failures.yaml")
    yaml_keys: set[tuple[str, str, str]] = set()
    if os.path.exists(failures_path):
        try:
            with open(failures_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            entries = []
            if isinstance(data, dict):
                entries = data.get("failures") or []
            elif isinstance(data, list):
                entries = data
            for entry in entries:
                if isinstance(entry, dict):
                    task_id = str(entry.get("task") or entry.get("task_id") or "")
                    agent = str(entry.get("agent") or "")
                    date = str(entry.get("date") or entry.get("created_at") or "")
                    yaml_keys.add((task_id, agent, date))
        except Exception as exc:
            logger.warning("parity failures: could not parse failures.yaml: %s", exc)

    try:
        db_keys = {
            (str(r[0] or ""), str(r[1] or ""), str(r[2] or ""))
            for r in conn.execute("SELECT task_id, agent, created_at FROM failures").fetchall()
        }
    except sqlite3.Error as exc:
        logger.warning("parity failures: db read failed: %s", exc)
        db_keys = set()

    only_db = len(db_keys - yaml_keys)
    only_yaml = len(yaml_keys - db_keys)
    return TableDrift(table="failures", only_in_db=only_db, only_in_yaml=only_yaml, mismatched=0)


def _check_decisions(conn: sqlite3.Connection, project_dir: str) -> TableDrift:
    """Compare decisions.yaml entries against SQLite decisions rows."""
    decisions_path = os.path.join(project_dir, ".superharness", "decisions.yaml")
    yaml_keys: set[tuple[str, str, str]] = set()
    if os.path.exists(decisions_path):
        try:
            with open(decisions_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            entries = []
            if isinstance(data, dict):
                entries = data.get("decisions") or []
            elif isinstance(data, list):
                entries = data
            for entry in entries:
                if isinstance(entry, dict):
                    agent = str(entry.get("agent") or "")
                    task_id = str(entry.get("task") or entry.get("task_id") or "")
                    date = str(entry.get("date") or entry.get("created_at") or "")
                    yaml_keys.add((agent, task_id, date))
        except Exception as exc:
            logger.warning("parity decisions: could not parse decisions.yaml: %s", exc)

    try:
        db_keys = {
            (str(r[0] or ""), str(r[1] or ""), str(r[2] or ""))
            for r in conn.execute("SELECT agent, task_id, created_at FROM decisions").fetchall()
        }
    except sqlite3.Error as exc:
        logger.warning("parity decisions: db read failed: %s", exc)
        db_keys = set()

    only_db = len(db_keys - yaml_keys)
    only_yaml = len(yaml_keys - db_keys)
    return TableDrift(table="decisions", only_in_db=only_db, only_in_yaml=only_yaml, mismatched=0)


def _check_foreign_keys(conn: sqlite3.Connection) -> int:
    """Run PRAGMA foreign_key_check. Returns count of violations."""
    try:
        rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        return len(rows)
    except sqlite3.Error as exc:
        logger.warning("parity fk_check: failed: %s", exc)
        return 0


def _heal_tasks_db_to_yaml(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Re-enqueue upsert_task ops for tasks in DB missing from YAML. Idempotent."""
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    yaml_ids = {t["id"] for t in _load_yaml_list(contract_path, include_subtasks=True) if "id" in t}

    try:
        rows = conn.execute(
            "SELECT id, title, owner, status FROM tasks"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("heal_tasks: db read failed: %s", exc)
        return 0

    count = 0
    for row in rows:
        if row["id"] not in yaml_ids:
            try:
                existing = conn.execute(
                    "SELECT 1 FROM yaml_sync_queue WHERE status='pending' AND op_type='upsert_task'"
                    " AND json_extract(payload,'$.id')=?",
                    (row["id"],)
                ).fetchone()
                if existing:
                    continue
                yaml_sync.enqueue_op(
                    conn,
                    op_type="upsert_task",
                    payload={"id": row["id"], "title": row["title"],
                             "owner": row["owner"], "status": row["status"]},
                    now=now,
                )
                conn.commit()
                count += 1
            except StateError as exc:
                logger.warning("heal_tasks: enqueue failed for %s: %s", row["id"], exc)
    return count


def _heal_tasks_yaml_to_db(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Upsert tasks found in YAML but missing from SQLite (B4: closes YAML-ahead-of-SQLite gap)."""
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    yaml_tasks = _load_yaml_list(contract_path, include_subtasks=True)

    try:
        db_ids = {r[0] for r in conn.execute("SELECT id FROM tasks").fetchall()}
    except sqlite3.Error as exc:
        logger.warning("heal_tasks_yaml_to_db: db read failed: %s", exc)
        return 0

    from superharness.engine import tasks_dao
    from superharness.engine.tasks_dao import TaskRow

    count = 0
    for t in yaml_tasks:
        if not isinstance(t, dict):
            continue
        task_id = str(t.get("id") or "")
        if not task_id or task_id in db_ids:
            continue
        try:
            row = TaskRow(
                id=task_id,
                title=str(t.get("title") or task_id),
                owner=t.get("owner") or None,
                status=str(t.get("status") or "todo"),
                effort=t.get("effort"),
                project_path=project_dir,
                development_method=t.get("development_method"),
                acceptance_criteria=list(t.get("acceptance_criteria") or []),
                test_types=list(t.get("test_types") or []),
                out_of_scope=list(t.get("out_of_scope") or []),
                definition_of_done=list(t.get("definition_of_done") or []),
                context=t.get("context"),
                tdd=t.get("tdd"),
                version=int(t.get("version") or 1),
                created_at=str(t.get("created_at") or now),
                blocked_by=list(t.get("blocked_by") or []),
            )
            tasks_dao.upsert(conn, row)
            conn.commit()
            count += 1
        except Exception as exc:
            logger.warning("heal_tasks_yaml_to_db: upsert failed for %s: %s", task_id, exc)
    return count


def _heal_inbox(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Re-enqueue update_inbox ops for inbox rows missing from YAML. Idempotent."""
    inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    yaml_ids = {i["id"] for i in _load_yaml_list(inbox_path) if "id" in i}

    try:
        rows = conn.execute(
            "SELECT id, task_id, target_agent, status FROM inbox"
        ).fetchall()
    except sqlite3.Error as exc:
        logger.warning("heal_inbox: db read failed: %s", exc)
        return 0

    count = 0
    for row in rows:
        if row["id"] not in yaml_ids:
            try:
                existing = conn.execute(
                    "SELECT 1 FROM yaml_sync_queue WHERE status='pending' AND op_type='update_inbox'"
                    " AND json_extract(payload,'$.id')=?",
                    (row["id"],)
                ).fetchone()
                if existing:
                    continue
                yaml_sync.enqueue_op(
                    conn,
                    op_type="update_inbox",
                    payload={"id": row["id"], "task_id": row["task_id"],
                             "target_agent": row["target_agent"], "status": row["status"]},
                    now=now,
                )
                conn.commit()
                count += 1
            except StateError as exc:
                logger.warning("heal_inbox: enqueue failed for %s: %s", row["id"], exc)
    return count


def _heal_tasks_mismatched(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Update SQLite task rows whose status/owner/title differ from YAML (YAML is authoritative)."""
    contract_path = os.path.join(project_dir, ".superharness", "contract.yaml")
    yaml_tasks = {
        t["id"]: t for t in _load_yaml_list(contract_path, include_subtasks=True) if "id" in t
    }
    try:
        db_rows = conn.execute("SELECT id, status, owner, title FROM tasks").fetchall()
    except sqlite3.Error as exc:
        logger.warning("heal_tasks_mismatched: db read failed: %s", exc)
        return 0

    count = 0
    for row in db_rows:
        tid = row["id"]
        if tid not in yaml_tasks:
            continue
        y = yaml_tasks[tid]
        # Normalize using the same write-time values to ensure idempotency
        db_status_n = str(row["status"] or "todo")
        y_status_n = str(y.get("status") or "todo")
        y_title_n = str(y.get("title") or tid)
        db_sig = _stable_hash(db_status_n, row["owner"], row["title"])
        y_sig = _stable_hash(y_status_n, y.get("owner"), y_title_n)
        if db_sig == y_sig:
            continue
        try:
            conn.execute(
                "UPDATE tasks SET status=?, owner=?, title=? WHERE id=?",
                (y_status_n, y.get("owner"), y_title_n, tid),
            )
            conn.commit()
            count += 1
        except sqlite3.Error as exc:
            logger.warning("heal_tasks_mismatched: update failed for %s: %s", tid, exc)
    return count


def _heal_inbox_yaml_to_db(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Insert inbox items found in YAML but missing from SQLite."""
    inbox_path = os.path.join(project_dir, ".superharness", "inbox.yaml")
    yaml_items = _load_yaml_list(inbox_path)
    try:
        db_ids = {r[0] for r in conn.execute("SELECT id FROM inbox").fetchall()}
    except sqlite3.Error as exc:
        logger.warning("heal_inbox_yaml_to_db: db read failed: %s", exc)
        return 0

    count = 0
    for item in yaml_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "")
        if not item_id or item_id in db_ids:
            continue
        try:
            conn.execute(
                """INSERT OR IGNORE INTO inbox
                   (id, task_id, target_agent, status, priority, max_retries, project_path, plan_only, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item_id,
                    str(item.get("task") or item.get("task_id") or ""),
                    str(item.get("to") or item.get("target_agent") or ""),
                    str(item.get("status") or "pending"),
                    int(item.get("priority") or 2),
                    int(item.get("max_retries") or 3),
                    str(item.get("project") or item.get("project_path") or project_dir),
                    1 if item.get("plan_only") else 0,
                    str(item.get("created_at") or now),
                ),
            )
            conn.commit()
            count += 1
        except sqlite3.Error as exc:
            logger.warning("heal_inbox_yaml_to_db: insert failed for %s: %s", item_id, exc)
    return count


def _heal_handoffs_yaml_to_db(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Import handoff YAML files into SQLite for rows not yet recorded there.

    Key used for dedup: (task_id, date) — must match what _check_handoffs computes.
    Files without a 'date' field use empty-string key, matching the parity checker.
    """
    handoffs_dir = os.path.join(project_dir, ".superharness", "handoffs")
    if not os.path.isdir(handoffs_dir):
        return 0

    try:
        db_keys = {
            (r[0], r[1])
            for r in conn.execute("SELECT task_id, created_at FROM handoffs").fetchall()
        }
    except sqlite3.Error as exc:
        logger.warning("heal_handoffs_yaml_to_db: db read failed: %s", exc)
        return 0

    # Pre-fetch task_ids that exist in SQLite so we can skip orphaned handoffs.
    try:
        existing_task_ids = {r[0] for r in conn.execute("SELECT id FROM tasks").fetchall()}
    except sqlite3.Error:
        existing_task_ids = set()

    count = 0
    for fname in os.listdir(handoffs_dir):
        if not fname.endswith(".yaml"):
            continue
        fpath = os.path.join(handoffs_dir, fname)
        try:
            with open(fpath, encoding="utf-8") as f:
                h = yaml.safe_load(f)
            if not isinstance(h, dict):
                continue
            task_id = str(h.get("task_id") or h.get("task") or "")
            # Use same key logic as _check_handoffs: date only, no timestamp fallback
            date = str(h.get("date") or "")
            if not task_id:
                continue
            if (task_id, date) in db_keys:
                continue
            # Skip handoffs whose task_id doesn't exist — would violate FK constraint
            if task_id not in existing_task_ids:
                continue
            conn.execute(
                """INSERT OR IGNORE INTO handoffs
                   (task_id, phase, status, from_agent, to_agent, content, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    task_id,
                    str(h.get("phase") or "report"),
                    str(h.get("status") or ""),
                    h.get("from"),
                    str(h.get("to") or ""),
                    None,
                    "{}",
                    date,  # use date as-is (even empty string) to match parity checker key
                ),
            )
            conn.commit()
            db_keys.add((task_id, date))
            count += 1
        except Exception as exc:
            logger.debug("heal_handoffs_yaml_to_db: skipped %s: %s", fname, exc)
    return count


def _heal_failures_yaml_to_db(conn: sqlite3.Connection, project_dir: str, now: str) -> int:
    """Import failures.yaml entries into SQLite for rows not yet recorded there."""
    failures_path = os.path.join(project_dir, ".superharness", "failures.yaml")
    if not os.path.exists(failures_path):
        return 0

    try:
        with open(failures_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        entries = []
        if isinstance(data, dict):
            entries = data.get("failures") or []
        elif isinstance(data, list):
            entries = data
    except Exception as exc:
        logger.warning("heal_failures_yaml_to_db: could not parse failures.yaml: %s", exc)
        return 0

    try:
        db_keys = {
            (str(r[0] or ""), str(r[1] or ""), str(r[2] or ""))
            for r in conn.execute("SELECT task_id, agent, created_at FROM failures").fetchall()
        }
    except sqlite3.Error as exc:
        logger.warning("heal_failures_yaml_to_db: db read failed: %s", exc)
        return 0

    count = 0
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        task_id = str(entry.get("task") or entry.get("task_id") or "")
        agent = str(entry.get("agent") or "")
        date = str(entry.get("date") or entry.get("created_at") or "")
        if not task_id:
            continue
        if (task_id, agent, date) in db_keys:
            continue
        try:
            conn.execute(
                """INSERT OR IGNORE INTO failures
                   (task_id, agent, pattern, error_snippet, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    task_id,
                    agent,
                    str(entry.get("pattern") or entry.get("patterns") or ""),
                    str(entry.get("error_snippet") or entry.get("error") or ""),
                    date,
                ),
            )
            conn.commit()
            db_keys.add((task_id, agent, date))
            count += 1
        except sqlite3.Error as exc:
            logger.debug("heal_failures_yaml_to_db: insert failed: %s", exc)
    return count
