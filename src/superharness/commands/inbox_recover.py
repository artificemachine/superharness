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
    p.add_argument("--dry-run", action="store_true", default=False,
                   help="Preview stale items that would be recovered without mutating inbox.yaml")
    opts = p.parse_args(argv)

    inbox_file = os.path.join(opts.project, ".superharness", "inbox.yaml")
    if not os.path.exists(inbox_file):
        sys.exit(f"Inbox file not found: {inbox_file}")

    if opts.dry_run:
        # Delegate to preview function (read-only)
        _preview_recover(inbox_file, opts.timeout_minutes)
        sys.exit(0)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sys.exit(_recover(file=inbox_file, now=now, timeout_minutes=opts.timeout_minutes, action=opts.action))


def _preview_recover(inbox_file: str, timeout_minutes: int) -> None:
    """Print stale launched items without modifying inbox.yaml."""
    import yaml
    from superharness.engine.inbox import _process_alive  # type: ignore[attr-defined]

    try:
        with open(inbox_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"recover --dry-run: could not read inbox: {e}", file=sys.stderr)
        return

    items = data.get("items") or []
    now = datetime.now(timezone.utc)
    timeout_seconds = timeout_minutes * 60
    stale = []

    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")) != "launched":
            continue
        if _process_alive(item.get("pid")):
            continue
        launched_at = str(item.get("launched_at", ""))
        if not launched_at:
            continue
        try:
            launched_time = datetime.fromisoformat(launched_at.replace("Z", "+00:00"))
            elapsed = (now - launched_time).total_seconds()
            if elapsed >= timeout_seconds:
                stale.append((item.get("id", "?"), item.get("task", "?"),
                               int(elapsed // 60), item.get("pid")))
        except ValueError:
            stale.append((item.get("id", "?"), item.get("task", "?"), -1, item.get("pid")))

    if not stale:
        print(f"recover --dry-run: no stale launched items (timeout={timeout_minutes}m)")
        return

    print(f"recover --dry-run: {len(stale)} stale item(s) would be recovered:")
    for iid, task_id, age_min, pid in stale:
        pid_note = f"  pid={pid}" if pid else ""
        age_note = f"{age_min}m" if age_min >= 0 else "invalid_ts"
        print(f"  {iid}  task={task_id}  age={age_note}{pid_note}")


if __name__ == "__main__":
    main()
