"""inbox normalize command — drop/archive stale inbox rows."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from superharness.engine.inbox import normalize as _normalize


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="normalize")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--archive", action="store_true")
    p.add_argument("--drop-status", action="append", dest="drop_statuses", default=[])
    p.add_argument("--drop-id-prefix", action="append", dest="drop_prefixes", default=[])
    opts = p.parse_args(argv)

    inbox_file = os.path.join(opts.project, ".superharness", "inbox.yaml")
    archive_file = os.path.join(opts.project, ".superharness", "inbox.archive.yaml")

    if not os.path.exists(inbox_file):
        sys.exit(f"Inbox file not found: {inbox_file}")

    drop_statuses = opts.drop_statuses or ["stale"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if opts.archive else None

    rc = _normalize(
        file=inbox_file,
        drop_statuses=drop_statuses,
        drop_prefixes=opts.drop_prefixes,
        archive_file=archive_file if opts.archive else None,
        now=now,
    )
    if rc != 0:
        sys.exit(rc)
    print(f"Normalized inbox: {inbox_file}")


if __name__ == "__main__":
    main()
