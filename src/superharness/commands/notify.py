"""notify command — send alerts for watcher issues and retry-threshold breaches.

Exit codes in automated mode: 0 no alert, 10 alert or recovery sent (or
printed in --dry-run), 11 alert suppressed by cooldown/fingerprint, 12 no
channel confirmed delivery (the alert stays pending and is retried).
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


_DISABLED_DETAIL = "disabled by user"


def _operator_labels(project_dir: str) -> list[str]:
    """Labels of the operator services that own *project_dir*.

    Installed plists win because a service may predate the current
    deterministic hash; the deterministic label is the fallback when no
    plist is installed yet.
    """
    from superharness.engine.launchd_health import (
        operator_label_for_project,
        operator_labels_for_project,
    )

    return operator_labels_for_project(project_dir) or [
        operator_label_for_project(project_dir)
    ]


def _watcher_ok_darwin(project_dir: str) -> tuple[bool, str]:
    from superharness.engine.launchd_health import is_disabled

    enabled = [
        label for label in _operator_labels(project_dir) if not is_disabled(label)
    ]
    # An owner-disabled operator is an intentional stop, not an outage.
    if not enabled:
        return True, _DISABLED_DETAIL
    uid = os.getuid() if hasattr(os, "getuid") else 0
    failures: list[str] = []
    for label in enabled:
        ok, detail = _service_ok(uid, label)
        if ok:
            return True, detail
        failures.append(detail)
    return False, "; ".join(failures)


def _watcher_health(project_dir: str, sys_platform: str) -> tuple[bool, str]:
    """Combine the service probe with the heartbeat.

    A loaded service can still host a hung watcher, so a fresh heartbeat is
    required too. Off macOS there is no service probe and the heartbeat is
    the only signal. An owner-disabled operator stops writing heartbeats on
    purpose, so its stale heartbeat is not an outage.
    """
    from superharness.engine.operator import Operator

    service_detail = ""
    if sys_platform == "Darwin":
        service_ok, service_detail = _watcher_ok_darwin(project_dir)
        if not service_ok or service_detail == _DISABLED_DETAIL:
            return service_ok, service_detail
    heartbeat = Operator(project_dir).check_watcher_health()
    if not heartbeat.is_healthy:
        return False, heartbeat.message
    return True, service_detail or heartbeat.message


def _service_ok(uid: int, label: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["launchctl", "print", f"gui/{uid}/{label}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{label}: launchctl unavailable ({e})"
    if r.returncode != 0:
        return False, f"{label} not loaded"
    out = r.stdout
    state = next(
        (
            line.split("=", 1)[1].strip()
            for line in out.splitlines()
            if "state =" in line
        ),
        "",
    )
    last_exit = next(
        (
            line.split("=", 1)[1].strip()
            for line in out.splitlines()
            if "last exit code =" in line
        ),
        "",
    )
    ok = state in ("running", "active") or (
        state == "not running" and last_exit in ("0", "(never exited)")
    )
    return ok, f"{label} state={state or 'unknown'} exit={last_exit or 'unknown'}"


def _retry_high_ids(inbox_file: str, threshold: int) -> list[str]:
    """Return inbox item IDs whose retry_count >= threshold. Reads from SQLite."""
    active_statuses = {
        "pending",
        "launched",
        "running",
        "stale",
        "failed",
        "paused",
        "stopped",
    }
    ids: list[str] = []
    # Derive project_dir from inbox_file path (.superharness/inbox.yaml → project root)
    project_dir = os.path.dirname(os.path.dirname(inbox_file))
    try:
        from superharness.engine.state_reader import get_inbox_items

        items = get_inbox_items(project_dir)
    except Exception as e:
        logger.warning("notify.py unexpected error: %s", e, exc_info=True)
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


@dataclass
class _NotifyState:
    watcher_streak: int = 0
    last_sent_epoch: int = 0
    last_fingerprint: str = ""
    # True once a watcher-down alert was delivered and until its recovery
    # notification is delivered.
    watcher_alert_active: bool = False


def _read_state(state_file: str) -> _NotifyState:
    state = _NotifyState()
    if not os.path.isfile(state_file):
        return state
    with open(state_file) as f:
        for line in f:
            key, sep, value = line.strip().partition("=")
            if not sep:
                continue
            if key == "LAST_FINGERPRINT":
                state.last_fingerprint = value
                continue
            try:
                number = int(value)
            except ValueError:
                logger.warning("notify: ignoring malformed state line %r", line)
                continue
            if key == "WATCHER_DOWN_STREAK":
                state.watcher_streak = number
            elif key == "LAST_SENT_EPOCH":
                state.last_sent_epoch = number
            elif key == "WATCHER_ALERT_ACTIVE":
                state.watcher_alert_active = bool(number)
    return state


def _write_state(state_file: str, state: _NotifyState) -> None:
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as f:
        f.write(f"WATCHER_DOWN_STREAK={state.watcher_streak}\n")
        f.write(f"LAST_SENT_EPOCH={state.last_sent_epoch}\n")
        f.write(f"LAST_FINGERPRINT={state.last_fingerprint}\n")
        f.write(f"WATCHER_ALERT_ACTIVE={int(state.watcher_alert_active)}\n")


def _deliver(
    message: str, project_dir: str, sys_platform: str, webhook_url: str
) -> bool:
    """Send *message* through every available channel.

    Returns True only when at least one channel confirmed delivery: the
    configured backend reported success, the webhook returned 2xx, or the
    local desktop notifier exited 0.
    """
    delivered = False
    try:
        from superharness.engine.relay_client import dispatch_notification

        sent, backend = dispatch_notification(message)
        if sent:
            print(f"notify: sent via {backend}")
            delivered = True
    except Exception as e:
        logger.warning("notify: notification backend failed: %s", e, exc_info=True)

    if webhook_url and shutil.which("curl"):
        now_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        payload = json.dumps(
            {"project": project_dir, "timestamp": now_ts, "alerts": [message]}
        )
        r = subprocess.run(
            [
                "curl",
                "-fsS",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                payload,
                webhook_url,
            ],
            capture_output=True,
            check=False,
        )
        delivered = delivered or r.returncode == 0

    if sys_platform == "Darwin" and shutil.which("osascript"):
        # The message travels as an argv item, never inside the script text,
        # so a quote in a project path cannot break or inject AppleScript.
        r = subprocess.run(
            [
                "osascript",
                "-e",
                "on run argv",
                "-e",
                'display notification (item 1 of argv) with title "superharness"',
                "-e",
                "end run",
                message,
            ],
            capture_output=True,
            check=False,
        )
        delivered = delivered or r.returncode == 0
    elif sys_platform == "Linux" and shutil.which("notify-send"):
        r = subprocess.run(
            ["notify-send", "superharness", message], capture_output=True, check=False
        )
        delivered = delivered or r.returncode == 0
    return delivered


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(prog="notify")
    p.add_argument("-p", "--project", default=os.getcwd())
    p.add_argument(
        "-m",
        "--message",
        default="",
        dest="message",
        help="Send a custom message instead of automated alerts",
    )
    p.add_argument("--retry-threshold", type=int, default=3, dest="retry_threshold")
    p.add_argument(
        "--watcher-down-streak", type=int, default=3, dest="watcher_down_streak"
    )
    p.add_argument("--cooldown-minutes", type=int, default=30, dest="cooldown_minutes")
    p.add_argument("--webhook-url", default="", dest="webhook_url")
    p.add_argument("--state-file", default="", dest="state_file")
    p.add_argument("--dry-run", action="store_true")
    opts = p.parse_args(argv)

    if opts.message:
        # Custom message mode — skip all automated checks, just send.
        project_dir = os.path.realpath(opts.project)
        message = opts.message
        if opts.dry_run:
            print("notify: dry-run")
            print(f"  → {message}")
            sys.exit(0)
        try:
            from superharness.engine.relay_client import dispatch_notification

            sent, backend = dispatch_notification(message)
            if sent:
                print(f"notify: sent via {backend}")
            else:
                print("notify: failed to send via any backend")
                sys.exit(1)
        except Exception as e:
            logger.warning("notify.py unexpected error: %s", e, exc_info=True)
            sys.exit(1)
        sys.exit(0)

    project_dir = os.path.realpath(opts.project)
    if not os.path.isdir(project_dir):
        sys.exit(f"Project directory does not exist: {opts.project}")

    harness_dir = os.path.join(project_dir, ".superharness")
    if not os.path.isdir(harness_dir):
        sys.exit(f"Missing .superharness in project: {project_dir}")

    sys.exit(
        evaluate_alerts(
            project_dir,
            retry_threshold=opts.retry_threshold,
            watcher_down_streak=opts.watcher_down_streak,
            cooldown_minutes=opts.cooldown_minutes,
            webhook_url=opts.webhook_url,
            state_file=opts.state_file,
            dry_run=opts.dry_run,
        )
    )


def evaluate_alerts(
    project_dir: str,
    *,
    retry_threshold: int = 3,
    watcher_down_streak: int = 3,
    cooldown_minutes: int = 30,
    webhook_url: str = "",
    state_file: str = "",
    dry_run: bool = False,
) -> int:
    """Evaluate and deliver the alerts for one project; return the exit code.

    Shared by `shux notify` and the launchd watchdog (`operator heal
    --notify`), which must call it in-process: the codes below are alert
    outcomes, not process failures.
    """
    harness_dir = os.path.join(project_dir, ".superharness")
    inbox_file = os.path.join(harness_dir, "inbox.yaml")
    state_file = state_file or os.path.join(harness_dir, "notify.state")

    # Platform watcher check
    sys_platform = platform.system()
    watcher_ok, watcher_detail = _watcher_health(project_dir, sys_platform)

    # Inbox retry check
    retry_ids = _retry_high_ids(inbox_file, retry_threshold)

    prev = _read_state(state_file)
    watcher_streak = 0 if watcher_ok else prev.watcher_streak + 1
    watcher_alerting = not watcher_ok and watcher_streak >= watcher_down_streak

    alerts: list[str] = []
    if watcher_alerting:
        alerts.append(f"watcher_down:{watcher_streak} ({watcher_detail})")
    if retry_ids:
        alerts.append(
            f"retry_threshold:{len(retry_ids)} item(s) >= {retry_threshold} [{','.join(retry_ids[:10]) or 'none'}]"
        )
    recovery = watcher_ok and prev.watcher_alert_active

    now_epoch = int(time.time())
    cooldown_seconds = cooldown_minutes * 60
    # The fingerprint names the outage kind, never the streak count: a
    # counter that grows every run would defeat the cooldown.
    fingerprint = f"watcher={int(watcher_alerting)}|retry={len(retry_ids)}:{','.join(retry_ids[:10])}"
    should_send = bool(alerts) and (
        prev.last_fingerprint != fingerprint
        or (now_epoch - prev.last_sent_epoch) >= cooldown_seconds
    )

    # Persist the streak before sending, so a crash mid-send cannot lose it.
    state = _NotifyState(
        watcher_streak,
        prev.last_sent_epoch,
        prev.last_fingerprint,
        prev.watcher_alert_active,
    )
    _write_state(state_file, state)

    if not alerts and not recovery:
        print(
            f"notify: no alerts (watcher_ok={int(watcher_ok)} retry_high={len(retry_ids)})"
        )
        return 0

    parts = list(alerts) if should_send else []
    if recovery:
        parts.insert(0, f"watcher_recovered ({watcher_detail})")
    if not parts:
        print("notify: alert suppressed by cooldown/fingerprint")
        print(f"superharness alert for {project_dir}: {'; '.join(alerts)}")
        return 11
    message = f"superharness alert for {project_dir}: {'; '.join(parts)}"
    print(message)

    if dry_run:
        # A dry run never consumes the alert: the sent state stays as it was.
        print("notify: dry-run")
        return 10

    if not _deliver(message, project_dir, sys_platform, webhook_url):
        print("notify: failed to deliver via any channel; will retry", file=sys.stderr)
        return 12

    state.last_sent_epoch = now_epoch
    if should_send:
        state.last_fingerprint = fingerprint
    if watcher_alerting:
        state.watcher_alert_active = True
    elif recovery:
        state.watcher_alert_active = False
    _write_state(state_file, state)
    return 10


if __name__ == "__main__":
    main()
