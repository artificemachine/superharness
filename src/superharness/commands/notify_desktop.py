"""Desktop notifications — native macOS/Linux alerts for task events."""
from __future__ import annotations

import os
import platform
import subprocess
import sys


def send_notification(title: str, message: str, sound: bool = True) -> bool:
    """Send a native desktop notification. Returns True on success."""
    system = platform.system()

    if system == "Darwin":
        script = f'display notification "{_escape(message)}" with title "{_escape(title)}"'
        if sound:
            script += ' sound name "Ping"'
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, check=False,
        )
        return r.returncode == 0

    if system == "Linux":
        r = subprocess.run(
            ["notify-send", title, message],
            capture_output=True, check=False,
        )
        return r.returncode == 0

    return False


def notify_task_event(task_id: str, status: str, agent: str = "") -> bool:
    """Send a notification for a task status change."""
    icons = {
        "done": "✅", "failed": "❌", "paused": "⏸",
        "waiting_input": "🤚", "report_ready": "📝",
        "review_requested": "🔍", "review_passed": "✅", "review_failed": "❌",
    }
    icon = icons.get(status, "📋")
    title = f"{icon} superharness — {status.replace('_', ' ')}"
    message = f"Task: {task_id}"
    if agent:
        message += f" ({agent})"
    return send_notification(title, message)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(prog="notify-desktop")
    parser.add_argument("--title", default="superharness")
    parser.add_argument("--message", required=True)
    parser.add_argument("--no-sound", action="store_true")
    opts = parser.parse_args(argv)

    ok = send_notification(opts.title, opts.message, sound=not opts.no_sound)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
