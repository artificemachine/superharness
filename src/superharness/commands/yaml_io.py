"""shux export-yaml / shux import-yaml — YAML snapshot tools.

Post-migration: generates human-readable YAML files from SQLite state
for inspection, backup, or interop with older superharness versions.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import yaml


def _now_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def export_yaml(project_dir: str, *, out_dir: str | None = None, all_: bool = False) -> int:
    """Generate snapshot YAML files from current SQLite state.

    Always exports inbox and contract. With --all, also exports handoffs,
    failures, and decisions.
    """
    if out_dir is None:
        out_dir = os.path.join(project_dir, ".superharness", "export")
    os.makedirs(out_dir, exist_ok=True)

    try:
        from dataclasses import asdict
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao, tasks_dao
        conn = get_connection(project_dir)
        try:
            init_db(conn)
            raw_inbox = [asdict(r) for r in inbox_dao.get_all(conn)]
            task_rows = [asdict(r) for r in tasks_dao.get_all(conn)]
        finally:
            conn.close()
    except Exception as exc:
        print(f"export-yaml: failed to read SQLite: {exc}", file=sys.stderr)
        return 1

    # Inbox
    inbox_rows = [_inbox_row_to_yaml_shape(r) for r in raw_inbox]
    inbox_path = os.path.join(out_dir, "inbox.yaml")
    try:
        with open(inbox_path, "w", encoding="utf-8") as f:
            f.write("# Delegation inbox (exported from SQLite)\n")
            f.write("# status: pending|launched|running|done|failed|stale\n")
            yaml.dump(inbox_rows, f, default_flow_style=False, allow_unicode=True)
        print(f"export-yaml: inbox → {inbox_path} ({len(inbox_rows)} items)")
    except OSError as exc:
        print(f"export-yaml: failed: {exc}", file=sys.stderr)
        return 1

    # Contract
    contract_path = os.path.join(out_dir, "contract.yaml")
    try:
        with open(contract_path, "w", encoding="utf-8") as f:
            yaml.dump({"tasks": task_rows}, f, default_flow_style=False, allow_unicode=True)
        print(f"export-yaml: contract → {contract_path} ({len(task_rows)} tasks)")
    except OSError as exc:
        print(f"export-yaml: failed: {exc}", file=sys.stderr)
        return 1

    if not all_:
        return 0

    # Handoffs (--all)
    try:
        from dataclasses import asdict as _asdict2
        from superharness.engine.db import get_connection as gc2, init_db as idb2
        from superharness.engine import tasks_dao as td2, handoffs_dao as hd2
        conn2 = gc2(project_dir)
        try:
            idb2(conn2)
            all_task_ids = [t.id for t in td2.get_all(conn2)]
            handoffs = []
            for tid in all_task_ids:
                handoffs.extend(_asdict2(r) for r in hd2.get_history(conn2, tid))
        finally:
            conn2.close()
        handoffs_dir = os.path.join(out_dir, "handoffs")
        os.makedirs(handoffs_dir, exist_ok=True)
        n = 0
        for h in handoffs:
            tid = str(h.get("task_id", "unknown")).replace("/", "-")
            ts = str(h.get("created_at", ""))[:10]
            fname = f"{tid}_{ts}.yaml"
            with open(os.path.join(handoffs_dir, fname), "w", encoding="utf-8") as f:
                yaml.dump(h, f, default_flow_style=False, allow_unicode=True)
            n += 1
        print(f"export-yaml: handoffs → {handoffs_dir} ({n} files)")
    except Exception as exc:
        print(f"export-yaml: handoffs export failed: {exc}", file=sys.stderr)

    # Failures (--all)
    try:
        from dataclasses import asdict as _asdict3
        from superharness.engine.db import get_connection as gc3, init_db as idb3
        from superharness.engine import failures_dao as fd3
        conn3 = gc3(project_dir)
        try:
            idb3(conn3)
            failures = [_asdict3(r) for r in fd3.get_recent(conn3, limit=1000)]
        finally:
            conn3.close()
        failures_path = os.path.join(out_dir, "failures.yaml")
        with open(failures_path, "w", encoding="utf-8") as f:
            yaml.dump({"failures": failures}, f, default_flow_style=False, allow_unicode=True)
        print(f"export-yaml: failures → {failures_path} ({len(failures)} entries)")
    except Exception as exc:
        print(f"export-yaml: failures export failed: {exc}", file=sys.stderr)

    # Decisions (--all)
    try:
        from dataclasses import asdict as _asdict4
        from superharness.engine.db import get_connection as gc4, init_db as idb4
        from superharness.engine import decisions_dao as dd4
        conn4 = gc4(project_dir)
        try:
            idb4(conn4)
            decisions = [_asdict4(r) for r in dd4.get_recent(conn4, limit=1000)]
        finally:
            conn4.close()
        decisions_path = os.path.join(out_dir, "decisions.yaml")
        with open(decisions_path, "w", encoding="utf-8") as f:
            yaml.dump(decisions, f, default_flow_style=False, allow_unicode=True)
        print(f"export-yaml: decisions → {decisions_path} ({len(decisions)} entries)")
    except Exception as exc:
        print(f"export-yaml: decisions export failed: {exc}", file=sys.stderr)

    return 0


def import_yaml(project_dir: str, *, source_dir: str) -> int:
    """Bulk-load YAML state files into SQLite.

    Reads contract.yaml, inbox.yaml from source_dir and upserts into
    the project's SQLite DB.
    """
    from superharness.engine.db import get_connection, init_db, transaction

    contract_src = os.path.join(source_dir, "contract.yaml")
    inbox_src = os.path.join(source_dir, "inbox.yaml")

    try:
        conn = get_connection(project_dir)
        init_db(conn)
    except Exception as exc:
        print(f"import-yaml: cannot open SQLite: {exc}", file=sys.stderr)
        return 1

    count_tasks = 0
    count_inbox = 0
    errors: list[str] = []

    # Import tasks from contract.yaml
    if os.path.isfile(contract_src):
        try:
            with open(contract_src, encoding="utf-8") as f:
                doc = yaml.safe_load(f) or {}
            tasks = doc.get("tasks") or []
            from superharness.engine import tasks_dao
            from superharness.engine.contract_io import _task_row_from_dict
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with transaction(conn):
                for t in tasks:
                    if not isinstance(t, dict) or not str(t.get("id", "")):
                        continue
                    row = _task_row_from_dict(t, project_dir, now)
                    tasks_dao.upsert(conn, row)
                    count_tasks += 1
                    for st in t.get("subtasks") or []:
                        if isinstance(st, dict) and str(st.get("id", "")):
                            tasks_dao.upsert(conn, _task_row_from_dict(st, project_dir, now))
                            count_tasks += 1
            conn.commit()
            print(f"import-yaml: tasks → {count_tasks} imported")
        except Exception as exc:
            errors.append(f"tasks: {exc}")

    # Import inbox from inbox.yaml
    if os.path.isfile(inbox_src):
        try:
            with open(inbox_src, encoding="utf-8") as f:
                items = yaml.safe_load(f) or []
            if not isinstance(items, list):
                items = []
            from superharness.engine import inbox_dao
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            with transaction(conn):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    inbox_dao.enqueue(
                        conn,
                        id=str(item.get("id", "")),
                        task_id=str(item.get("task", item.get("task_id", ""))),
                        target_agent=str(item.get("to", item.get("target_agent", ""))),
                        priority=int(item.get("priority", 2)),
                        max_retries=int(item.get("max_retries", 3)),
                        project_path=item.get("project", item.get("project_path")),
                        plan_only=bool(item.get("plan_only", False)),
                        now=item.get("created_at", now),
                    )
                    count_inbox += 1
            conn.commit()
            print(f"import-yaml: inbox → {count_inbox} imported")
        except Exception as exc:
            errors.append(f"inbox: {exc}")

    conn.close()

    if errors:
        for e in errors:
            print(f"import-yaml: error: {e}", file=sys.stderr)
        return 1

    return 0


def _inbox_row_to_yaml_shape(row: dict) -> dict:
    """Translate SQLite field names to YAML field names."""
    out = dict(row)
    out["task"] = out.pop("task_id", out.get("task", ""))
    out["to"] = out.pop("target_agent", out.get("to", ""))
    out["project"] = out.pop("project_path", out.get("project"))
    return out


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="yaml-io",
        description="Export YAML snapshots from SQLite, or import YAML into SQLite",
    )
    sub = parser.add_subparsers(dest="action", required=True)

    exp = sub.add_parser("export", help="Export YAML snapshot from SQLite")
    exp.add_argument("--project", "-p", default=".", help="Project directory")
    exp.add_argument("--out-dir", help="Output directory (default: .superharness/export/)")
    exp.add_argument("--all", action="store_true", help="Include handoffs, failures, decisions")

    imp = sub.add_parser("import", help="Import YAML state files into SQLite")
    imp.add_argument("--project", "-p", default=".", help="Project directory")
    imp.add_argument("--source-dir", required=True, help="Directory containing YAML state files")

    args = parser.parse_args(argv)
    project_dir = os.path.abspath(args.project)

    if args.action == "export":
        sys.exit(export_yaml(project_dir, out_dir=getattr(args, "out_dir", None), all_=args.all))
    elif args.action == "import":
        sys.exit(import_yaml(project_dir, source_dir=args.source_dir))
