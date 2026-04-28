"""Recover stale launched inbox items — reads from SQLite via state_reader."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="recover")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--timeout-minutes", type=int, default=20, dest="timeout_minutes")
    p.add_argument("--action", default="stale", choices=["stale", "retry"])
    p.add_argument("--dry-run", action="store_true", default=False)
    opts = p.parse_args(argv)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if opts.dry_run:
        _preview_recover(opts.project, opts.timeout_minutes)
        sys.exit(0)

    sys.exit(_recover(project_dir=opts.project, now=now, timeout_minutes=opts.timeout_minutes, action=opts.action))


def _preview_recover(project_dir: str, timeout_minutes: int) -> None:
    """Print stale launched items without modifying state."""
    from superharness.engine.state_reader import get_inbox_items
    items = get_inbox_items(project_dir)
    now = datetime.now(timezone.utc)
    timeout_seconds = timeout_minutes * 60
    count = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "launched":
            continue
        launched_at = item.get("launched_at", "")
        if not launched_at:
            continue
        try:
            ts = datetime.fromisoformat(str(launched_at).replace("Z", "+00:00"))
            if (now - ts).total_seconds() >= timeout_seconds:
                print(f"  would recover: {item.get('id')} ({item.get('task', '')}) launched {launched_at}")
                count += 1
        except (ValueError, TypeError):
            pass

    print(f"recover --dry-run: {count} item(s) would be recovered")


def _recover(*, project_dir: str, now: str, timeout_minutes: int, action: str) -> int:
    """Recover stale launched items by writing to SQLite."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import inbox_dao
    from superharness.engine.state_reader import get_inbox_items

    items = get_inbox_items(project_dir)
    timeout_seconds = timeout_minutes * 60
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    updated = 0

    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "launched":
            continue
        launched_at = item.get("launched_at", "")
        if not launched_at:
            continue
        try:
            ts = datetime.fromisoformat(str(launched_at).replace("Z", "+00:00"))
            if (now_dt - ts).total_seconds() < timeout_seconds:
                continue
        except (ValueError, TypeError):
            continue

        to_status = "pending" if action == "retry" else "stale"
        try:
            conn = get_connection(project_dir)
            try:
                init_db(conn)
                inbox_dao.update_status(conn, item.get("id", ""), from_status="launched", to_status=to_status, now=now)
                conn.commit()
                updated += 1
                print(f"recover: {item.get('id')} ({item.get('task', '')}) → {to_status}")
            finally:
                conn.close()
        except Exception as e:
            print(f"recover: failed for {item.get('id')}: {e}", file=sys.stderr)

    return 0 if updated > 0 else 0
