"""Inbox garbage collector — reconcile stale inbox items against contract status."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


# Inbox statuses eligible for GC (terminal-but-stale)
GC_ELIGIBLE = {"stopped", "failed", "stale", "paused"}


def run_gc(project_dir: str | Path, dry_run: bool = False) -> dict:
    """Reconcile inbox items against contract tasks.

    For each inbox item in a GC-eligible status (stopped/failed/stale/paused),
    check if the corresponding contract task is done. If so, mark the inbox
    item as done.

    Returns dict with reconciled count and details.
    """
    project_dir = Path(project_dir)
    harness = project_dir / ".superharness"
    inbox_file = harness / "inbox.yaml"
    contract_file = harness / "contract.yaml"
    ledger_file = harness / "ledger.md"

    if not inbox_file.exists() or not contract_file.exists():
        return {"reconciled": 0, "would_reconcile": 0, "items": []}

    contract = yaml.safe_load(contract_file.read_text()) or {}
    task_statuses = {}
    for t in contract.get("tasks") or []:
        if isinstance(t, dict):
            task_statuses[str(t.get("id", ""))] = str(t.get("status", ""))

    items = yaml.safe_load(inbox_file.read_text()) or []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    reconciled = 0
    would_reconcile = 0
    details = []

    for item in items:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", ""))
        task_id = str(item.get("task", ""))
        item_id = str(item.get("id", ""))

        if status not in GC_ELIGIBLE:
            continue

        task_status = task_statuses.get(task_id, "")
        if task_status != "done":
            continue

        if dry_run:
            would_reconcile += 1
            details.append({"item_id": item_id, "task": task_id, "from": status, "action": "would_mark_done"})
            print(f"[dry-run] would reconcile: {item_id} ({status} → done, task {task_id} is done)")
        else:
            item["status"] = "done"
            item["done_at"] = now
            item["gc_reconciled"] = True
            reconciled += 1
            details.append({"item_id": item_id, "task": task_id, "from": status, "action": "marked_done"})
            print(f"Reconciled: {item_id} ({status} → done, task {task_id} is done)")

            if ledger_file.exists():
                with open(ledger_file, "a") as f:
                    f.write(f"- {now} — [gc] — reconciled inbox item {item_id}: {status} → done (task {task_id} is done)\n")

    if not dry_run and reconciled > 0:
        inbox_file.write_text(yaml.dump(items, default_flow_style=False))

    print(f"\nInbox GC: {reconciled} reconciled, {would_reconcile} would reconcile")
    return {"reconciled": reconciled, "would_reconcile": would_reconcile, "items": details}


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="inbox-gc",
        description="Reconcile stale inbox items against contract task status",
    )
    parser.add_argument("--project", "-p", default=None,
                        help="Project directory (default: cwd)")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Show what would be reconciled without modifying")
    opts = parser.parse_args(argv)

    project = os.path.realpath(opts.project or os.getcwd())
    result = run_gc(project, dry_run=opts.dry_run)
    sys.exit(0 if result["reconciled"] >= 0 else 1)


if __name__ == "__main__":
    main()
