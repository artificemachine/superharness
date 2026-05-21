"""MCP EventStream — Iteration 4.

Reads and writes events.jsonl for per-project event streaming.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import logging
logger = logging.getLogger(__name__)


def _events_path(project_path: str) -> str:
    return os.path.join(project_path, ".superharness", "events.jsonl")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventStream:
    """Read and write events.jsonl for a project."""

    def get_events(self, project_path: str, n: int = 50) -> list[dict]:
        """Return the last *n* events from events.jsonl."""
        path = _events_path(project_path)
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            result = []
            for line in lines[-n:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    result.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
            return result
        except Exception as e:
            logger.warning("events.py unexpected error: %s", e, exc_info=True)
            return []

    def append_event(self, project_path: str, payload: dict) -> None:
        """Append a JSONL event line to events.jsonl."""
        path = _events_path(project_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        record = {"ts": _now_utc(), **payload}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def stream_logs(self, project_path: str, task_id: str):
        """Generator: yield new lines appended to runs/<task_id>.log."""
        log_path = os.path.join(project_path, ".superharness", "runs", f"{task_id}.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        import time
        with open(log_path, "a+", encoding="utf-8", errors="replace") as f:
            f.seek(0, 2)  # seek to end
            while True:
                line = f.readline()
                if line:
                    yield line.rstrip("\n")
                else:
                    time.sleep(0.1)
