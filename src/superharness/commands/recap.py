"""recap command — what happened in the last N hours."""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml


def _parse_iso(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _within_window(ts: str, cutoff: datetime) -> bool:
    dt = _parse_iso(ts)
    return dt is not None and dt >= cutoff


def run_recap(project_dir: str | Path, hours: int = 4) -> dict:
    """Summarize what happened in the last N hours."""
    project_dir = Path(project_dir)
    harness = project_dir / ".superharness"
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=hours)

    sections: list[str] = []
    summary = {"hours": hours, "tasks_changed": 0, "inbox_events": 0, "ledger_lines": 0, "handoffs": 0}

    # 1. Ledger entries
    ledger_file = harness / "ledger.md"
    recent_ledger: list[str] = []
    if ledger_file.exists():
        for line in ledger_file.read_text().splitlines():
            match = re.search(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?)", line)
            if match and _within_window(match.group(1), cutoff):
                recent_ledger.append(line.strip())
    if recent_ledger:
        sections.append("## Ledger")
        for line in recent_ledger[-20:]:
            sections.append(f"  {line}")
        summary["ledger_lines"] = len(recent_ledger)

    # 2. Inbox activity
    recent_inbox: list[dict] = []
    try:
        from superharness.engine.state_reader import get_inbox_items
        items = get_inbox_items(str(project_dir))
        for item in items:
            if not isinstance(item, dict):
                continue
            for ts_key in ("created_at", "launched_at", "done_at", "failed_at", "paused_at", "stopped_at"):
                ts = str(item.get(ts_key, ""))
                if _within_window(ts, cutoff):
                    recent_inbox.append(item)
                    break
    except Exception:
        pass
    if recent_inbox:
        sections.append("## Inbox Activity")
        for item in recent_inbox[-15:]:
            task = item.get("task", "?")
            status = item.get("status", "?")
            to = item.get("to", "?")
            reason = item.get("pause_reason") or item.get("failed_reason") or ""
            reason_str = f" ({reason.replace('_', ' ')})" if reason else ""
            sections.append(f"  {status:10s} {task} → {to}{reason_str}")
        summary["inbox_events"] = len(recent_inbox)

    # 3. Recent handoffs
    handoff_dir = harness / "handoffs"
    recent_handoffs: list[tuple[str, str]] = []
    if handoff_dir.is_dir():
        for f in sorted(handoff_dir.iterdir()):
            if not f.suffix in (".yaml", ".md"):
                continue
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime >= cutoff:
                    recent_handoffs.append((f.name, mtime.strftime("%H:%M")))
            except OSError:
                continue
    if recent_handoffs:
        sections.append("## Handoffs")
        for name, time_str in recent_handoffs[-10:]:
            sections.append(f"  {time_str} {name}")
        summary["handoffs"] = len(recent_handoffs)

    # 4. Task status changes
    recent_tasks: list[str] = []
    try:
        from superharness.engine import state_reader as _sr
        tasks = _sr.get_tasks(str(project_dir))
    except Exception:
        tasks = []
    for task in tasks:
            if not isinstance(task, dict):
                continue
            status = task.get("status", "")
            tid = task.get("id", "")
            # Check timestamp fields for recency
            for ts_key in ("review_requested_at", "stopped_at", "verified_at"):
                ts = str(task.get(ts_key, ""))
                if _within_window(ts, cutoff):
                    recent_tasks.append(f"  {status:15s} {tid}")
                    break
    if recent_tasks:
        sections.append("## Task Changes")
        for line in recent_tasks:
            sections.append(line)
        summary["tasks_changed"] = len(recent_tasks)

    # Output
    header = f"## Recap — last {hours}h (since {cutoff.strftime('%H:%M UTC')})"
    print(header)
    print()
    if not sections:
        print("  Nothing happened.")
    else:
        for line in sections:
            print(line)
    print()
    total = summary["ledger_lines"] + summary["inbox_events"] + summary["handoffs"] + summary["tasks_changed"]
    print(f"Total: {total} events ({summary['ledger_lines']} ledger, {summary['inbox_events']} inbox, "
          f"{summary['handoffs']} handoffs, {summary['tasks_changed']} task changes)")

    return summary


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="recap", description="What happened in the last N hours")
    parser.add_argument("--project", "-p", default=None)
    parser.add_argument("--hours", "-n", type=int, default=4, help="Look back N hours (default: 4)")
    opts = parser.parse_args(argv)

    project = os.path.realpath(opts.project or os.getcwd())
    run_recap(project, hours=opts.hours)


if __name__ == "__main__":
    main()
