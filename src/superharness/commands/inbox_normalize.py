"""inbox normalize command — drop/archive stale inbox rows via SQLite."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="normalize")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--archive", action="store_true")
    p.add_argument("--drop-status", action="append", dest="drop_statuses", default=[])
    p.add_argument("--drop-id-prefix", action="append", dest="drop_prefixes", default=[])
    opts = p.parse_args(argv)

    project_dir = opts.project
    drop_statuses = opts.drop_statuses or ["stale"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    from superharness.engine.db import get_connection, init_db
    conn = get_connection(project_dir)
    try:
        init_db(conn)
        # Build query to find rows to drop
        placeholders = ",".join("?" * len(drop_statuses))
        rows = conn.execute(
            f"SELECT id, status FROM inbox WHERE status IN ({placeholders})",
            drop_statuses,
        ).fetchall()

        if opts.drop_prefixes:
            prefix_rows = conn.execute(
                "SELECT id, status FROM inbox WHERE status NOT IN (" + placeholders + ")",
                drop_statuses,
            ).fetchall()
            rows = list(rows) + [
                r for r in prefix_rows
                if any(str(r["id"]).startswith(p) for p in opts.drop_prefixes)
            ]

        removed = 0
        for row in rows:
            item_id = row["id"]
            from_status = row["status"]
            if opts.archive:
                # Mark as done (tombstone) instead of deleting
                if conn.execute(
                    "UPDATE inbox SET status='done', done_at=? WHERE id=? AND status=?",
                    (now, item_id, from_status)
                ).rowcount > 0:
                    removed += 1
            else:
                if conn.execute(
                    "DELETE FROM inbox WHERE id=? AND status=?",
                    (item_id, from_status)
                ).rowcount > 0:
                    removed += 1

        conn.commit()
        action = "archived" if opts.archive else "dropped"
        print(f"Normalized inbox: {action} {removed} item(s) from {project_dir}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
