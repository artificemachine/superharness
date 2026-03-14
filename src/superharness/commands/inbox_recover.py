"""inbox recover command — mark stale launched items."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from superharness.engine.inbox import recover_launched as _recover


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="recover")
    p.add_argument("-p", "--project", required=True)
    p.add_argument("--timeout-minutes", type=int, default=20, dest="timeout_minutes")
    p.add_argument("--action", default="stale", choices=["stale", "retry"])
    opts = p.parse_args(argv)

    inbox_file = os.path.join(opts.project, ".superharness", "inbox.yaml")
    if not os.path.exists(inbox_file):
        sys.exit(f"Inbox file not found: {inbox_file}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sys.exit(_recover(file=inbox_file, now=now, timeout_minutes=opts.timeout_minutes, action=opts.action))


if __name__ == "__main__":
    main()
