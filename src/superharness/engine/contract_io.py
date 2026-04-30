"""Canonical contract read/write path.

All contract-mutating commands must use write_contract() from this module.
Pydantic validation runs when pydantic is available; degrades gracefully when
it is not (e.g. minimal CI environments that install only core deps).
"""

from __future__ import annotations

import logging
import os
import tempfile

import yaml

logger = logging.getLogger(__name__)


class ContractValidationError(RuntimeError):
    """Raised when write_contract() is given a document that fails schema validation."""


try:
    from ruamel.yaml import YAML as RuamelYAML

    _RT_AVAILABLE = True
except ImportError:
    _RT_AVAILABLE = False

# Break-glass escape: SUPERHARNESS_SCHEMA_ENFORCEMENT=warn → logs at CRITICAL but still writes.
_ENFORCEMENT = os.environ.get("SUPERHARNESS_SCHEMA_ENFORCEMENT", "strict")


def _validate(doc: object) -> None:
    """Validate doc against Contract schema. No-op if pydantic is unavailable."""
    try:
        from pydantic import ValidationError
        from superharness.engine.schemas import Contract
    except ImportError:
        logger.debug("pydantic not available — contract schema validation skipped")
        return

    try:
        Contract.model_validate(doc)
    except ValidationError as exc:
        errs = "\n".join(
            f"  {'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        if _ENFORCEMENT == "warn":
            logger.critical(
                "SCHEMA ENFORCEMENT BYPASSED (SUPERHARNESS_SCHEMA_ENFORCEMENT=warn). "
                "Violations:\n%s",
                errs,
            )
        else:
            raise ContractValidationError(
                f"Refusing to write contract: {len(exc.errors())} schema violation(s)\n{errs}"
            ) from exc


def _task_row_from_dict(
    t: dict,
    project_dir: str,
    now: str,
) -> "TaskRow":
    from superharness.engine.tasks_dao import TaskRow

    task_id = str(t.get("id", ""))
    return TaskRow(
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
        plan_proposed_at=t.get("plan_proposed_at"),
        plan_approved_at=t.get("plan_approved_at"),
        in_progress_at=t.get("in_progress_at"),
        report_ready_at=t.get("report_ready_at"),
        review_requested_at=t.get("review_requested_at"),
        done_at=t.get("done_at"),
        cancelled_at=t.get("cancelled_at"),
        blocked_by=list(t.get("blocked_by") or []),
        verified=bool(t.get("verified", False)),
        verified_at=t.get("verified_at"),
        verified_by=t.get("verified_by"),
    )


def _sqlite_sync_tasks(path: str, doc: object) -> None:
    """Upsert all tasks from a freshly-written contract into SQLite. Never raises.

    Also recurses into nested subtasks so orchestrator decompositions stay in sync (B2).
    """
    try:
        if not isinstance(doc, dict):
            return
        tasks = doc.get("tasks") or []
        if not tasks:
            return
        # Derive project_dir from contract path: <project_dir>/.superharness/contract.yaml
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        from datetime import datetime, timezone
        from superharness.engine.db import get_connection, init_db, transaction
        from superharness.engine import tasks_dao

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            with transaction(conn):
                for t in tasks:
                    if not isinstance(t, dict):
                        continue
                    if not str(t.get("id", "")):
                        continue
                    tasks_dao.upsert(conn, _task_row_from_dict(t, project_dir, now))
                    for st in t.get("subtasks") or []:
                        if isinstance(st, dict) and str(st.get("id", "")):
                            tasks_dao.upsert(
                                conn, _task_row_from_dict(st, project_dir, now)
                            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass


def write_contract(path: str, doc: object) -> None:
    _validate(doc)

    from superharness.engine.sqlite_only import is_sqlite_only

    if is_sqlite_only():
        # SQLite-only mode: skip YAML file write, write directly to SQLite.
        _sqlite_sync_tasks(path, doc)
        return

    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            if _RT_AVAILABLE:
                rt = RuamelYAML()
                rt.preserve_quotes = True
                rt.default_flow_style = False
                rt.dump(doc, f)
            else:
                f.write(yaml.dump(doc, default_flow_style=False, allow_unicode=True))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        tmp = None
        _sqlite_sync_tasks(path, doc)
    finally:
        if tmp is not None and os.path.exists(tmp):
            os.unlink(tmp)


def read_contract(path: str) -> tuple[dict, list]:
    """Load contract document and return (doc, validation_errors).

    In sqlite_only mode (default since v1.43), reconstructs the doc from
    SQLite via state_reader.get_contract_doc instead of reading the
    tombstone contract.yaml. This keeps read and write paths consistent:
    write_contract upserts to SQLite, so read_contract must read from
    SQLite, otherwise out-of-band mutations done via `shux task status`
    are clobbered the next time anyone calls `shux task create` (which
    re-syncs the stale YAML over SQLite via _sqlite_sync_tasks).

    validation_errors is an empty list when pydantic is unavailable or
    schema is satisfied.
    """
    from superharness.engine.sqlite_only import is_sqlite_only

    if is_sqlite_only():
        from superharness.engine import state_reader
        # path is .../.superharness/contract.yaml; project_dir is two levels up.
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(path)))
        doc = state_reader.get_contract_doc(project_dir)
        # Preserve YAML-side metadata that SQLite does not currently mirror
        # (id, goal, created, created_by, status). state_reader returns only
        # `tasks`; merge with the YAML so callers that read top-level keys
        # still see them when the YAML exists alongside SQLite.
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    legacy = yaml.safe_load(f) or {}
                if isinstance(legacy, dict):
                    for k, v in legacy.items():
                        if k != "tasks":
                            doc.setdefault(k, v)
            except Exception:
                pass
        errors: list = []
        return doc, errors

    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    errors: list = []
    try:
        from pydantic import ValidationError
        from superharness.engine.schemas import Contract

        try:
            Contract.model_validate(doc)
        except ValidationError as exc:
            errors = exc.errors()
    except ImportError:
        pass
    return doc, errors
