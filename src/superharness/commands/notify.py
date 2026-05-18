"""notify command — send alerts for watcher issues and retry-threshold breaches."""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from superharness.engine.yaml_helpers import safe_load


def _watcher_ok_darwin(project_dir: str) -> tuple[bool, str]:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(project_dir))
    label = f"com.superharness.inbox.{slug}"
    uid = os.getuid() if hasattr(os, "getuid") else 0
    r = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        return False, "not loaded"
    out = r.stdout
    state = next((line.split("=", 1)[1].strip() for line in out.splitlines() if "state =" in line), "")
    last_exit = next((line.split("=", 1)[1].strip() for line in out.splitlines() if "last exit code =" in line), "")
    ok = state in ("running", "active") or (
        state == "not running" and last_exit in ("0", "(never exited)")
    )
    return ok, f"state={state or 'unknown'} exit={last_exit or 'unknown'}"


def _retry_high_ids(inbox_file: str, threshold: int) -> list[str]:
    """Return inbox item IDs whose retry_count >= threshold. Reads from SQLite."""
    active_statuses = {"pending", "launched", "running", "stale", "failed", "paused", "stopped"}
    ids: list[str] = []
    # Derive project_dir from inbox_file path (.superharness/inbox.yaml → project root)
    project_dir = os.path.dirname(os.path.dirname(inbox_file))
    try:
        from superharness.engine.state_reader import get_inbox_items
        items = get_inbox_items(project_dir)
    except Exception:
        return ids
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status", "") not in active_statuses:
            continue
        rc = int(item.get("retry_count") or 0)
        iid = str(item.get("id", ""))
        if rc >= threshold and iid:
            ids.append(iid)
    return ids


def _read_state(state_file: str) -> tuple[int, int, str]:
    """Returns (watcher_streak, last_sent_epoch, last_fingerprint)."""
    streak, last_sent, fingerprint = 0, 0, ""
    if not os.path.isfile(state_file):
        return streak, last_sent, fingerprint
    with open(state_file) as f:
        for line in f:
            line = line.strip()
            if line.startswith("WATCHER_DOWN_STREAK="):
                try:
                    streak = int(line.split("=", 1)[1])
                except ValueError:
                    pass
            elif line.startswith("LAST_SENT_EPOCH="):
                try:
                    last_sent = int(line.split("=", 1)[1])
                except ValueError:
                    pass
            elif line.startswith("LAST_FINGERPRINT="):
                fingerprint = line.split("=", 1)[1]
    return streak, last_sent, fingerprint


def _write_state(state_file: str, streak: int, last_sent: int, fingerprint: str) -> None:
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as f:
        f.write(f"WATCHER_DOWN_STREAK={streak}\n")
        f.write(f"LAST_SENT_EPOCH={last_sent}\n")
        f.write(f"LAST_FINGERPRINT={fingerprint}\n")


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="notify")
    p.add_argument("-p", "--project", default=os.getcwd())
    p.add_argument("--retry-threshold", type=int, default=3, dest="retry_threshold")
    p.add_argument("--watcher-down-streak", type=int, default=3, dest="watcher_down_streak")
    p.add_argument("--cooldown-minutes", type=int, default=30, dest="cooldown_minutes")
    p.add_argument("--webhook-url", default="", dest="webhook_url")
    p.add_argument("--state-file", default="", dest="state_file")
    p.add_argument("--dry-run", action="store_true")
    opts = p.parse_args(argv)

    if opts.retry_threshold <= 0 or opts.watcher_down_streak <= 0:
        sys.exit("--retry-threshold and --watcher-down-streak must be positive integers")

    project_dir = os.path.realpath(opts.project)
    if not os.path.isdir(project_dir):
        sys.exit(f"Project directory does not exist: {opts.project}")

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        sys.exit(f"Missing .superharness in project: {project_dir}")

    inbox_file = os.path.join(harness_dir, "inbox.yaml")
    state_file = opts.state_file or os.path.join(harness_dir, "notify.state")

    # Platform watcher check
    sys_platform = platform.system()
    watcher_ok, watcher_detail = True, ""
    if sys_platform == "Darwin":
        watcher_ok, watcher_detail = _watcher_ok_darwin(project_dir)

    # Inbox retry check
    retry_ids = _retry_high_ids(inbox_file, opts.retry_threshold)

    # Load previous state
    prev_streak, prev_last_sent, prev_fingerprint = _read_state(state_file)

    # Update watcher streak
    watcher_streak = 0 if watcher_ok else prev_streak + 1

    # Build alerts
    alerts: list[str] = []
    if not watcher_ok and watcher_streak >= opts.watcher_down_streak:
        alerts.append(f"watcher_down:{watcher_streak} ({watcher_detail})")
    if retry_ids:
        alerts.append(f"retry_threshold:{len(retry_ids)} item(s) >= {opts.retry_threshold} [{','.join(retry_ids[:10]) or 'none'}]")

    now_epoch = int(time.time())
    cooldown_seconds = opts.cooldown_minutes * 60
    fingerprint = f"watcher={int(watcher_ok)}:{watcher_streak}|retry={len(retry_ids)}:{','.join(retry_ids[:10])}"

    should_send = False
    if alerts:
        if prev_fingerprint != fingerprint:
            should_send = True
        elif (now_epoch - prev_last_sent) >= cooldown_seconds:
            should_send = True

    # Save state (pre-send, update streak)
    _write_state(state_file, watcher_streak, prev_last_sent, prev_fingerprint)

    if not alerts:
        print(f"notify: no alerts (watcher_ok={int(watcher_ok)} retry_high={len(retry_ids)})")
        sys.exit(0)

    message = f"superharness alert for {project_dir}: {'; '.join(alerts)}"

    if not should_send:
        print("notify: alert suppressed by cooldown/fingerprint")
        print(message)
        sys.exit(11)

    if opts.dry_run:
        print("notify: dry-run")
        print(message)
    else:
        print(message)
        # Configured backend (relay preferred → direct Telegram bot fallback)
        try:
            from superharness.engine.relay_client import dispatch_notification
            sent, backend = dispatch_notification(message)
            if sent:
                print(f"notify: sent via {backend}")
        except Exception:
            pass
        # Webhook fallback
        if opts.webhook_url and shutil.which("curl"):
            now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            payload = json.dumps({
                "project": project_dir,
                "timestamp": now_ts,
                "alerts": ["; ".join(alerts)],
            })
            subprocess.run(
                ["curl", "-fsS", "-X", "POST", "-H", "Content-Type: application/json", "-d", payload, opts.webhook_url],
                capture_output=True
            )
        # Desktop notification
        if sys_platform == "Darwin" and shutil.which("osascript"):
            subprocess.run(
                ["osascript", "-e", f'display notification "{message}" with title "superharness"'],
                capture_output=True
            )
        elif sys_platform == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "superharness", message], capture_output=True)

    # Update state post-send
    _write_state(state_file, watcher_streak, now_epoch, fingerprint)
    sys.exit(10)


if __name__ == "__main__":
    main()
