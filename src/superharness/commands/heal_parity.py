"""shux heal-parity — close drift between SQLite state and authoritative YAML.

Runs check_parity, then heal_parity. Prints a per-table report. Exit code is
0 when there is nothing to heal (or all heals enqueued/applied), non-zero only
on unexpected exceptions.
"""
from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="heal-parity",
        description="Close drift between SQLite state and authoritative YAML.",
    )
    p.add_argument("-p", "--project", default=os.getcwd(),
                   help="Project directory (default: current directory)")
    p.add_argument("--check", action="store_true",
                   help="Only report drift; do not heal.")
    opts = p.parse_args(argv)

    project_dir = os.path.realpath(opts.project)
    if not os.path.isdir(project_dir):
        print(f"error: project directory does not exist: {opts.project}", file=sys.stderr)
        return 2

    state_db = os.path.join(project_dir, ".superharness", "state.sqlite3")
    if not os.path.isfile(state_db):
        print(f"info: state.sqlite3 not present at {state_db} — nothing to heal")
        return 0

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import parity

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        report = parity.check_parity(conn, project_dir)
        print(f"parity: checked_at={report.checked_at} healthy={report.healthy}")
        for d in report.drifts:
            if d.only_in_db or d.only_in_yaml or d.mismatched:
                print(
                    f"  drift {d.table}: only_in_db={d.only_in_db}"
                    f" only_in_yaml={d.only_in_yaml} mismatched={d.mismatched}"
                )
        print(f"  yaml_sync_lag={report.yaml_sync_lag}")
        print(f"  foreign_key_violations={report.foreign_key_violations}")

        if opts.check:
            return 0 if report.healthy else 1

        if report.healthy:
            return 0

        healed = parity.heal_parity(conn, project_dir, report)
        print(f"heal: enqueued/upserted {healed} rows")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
