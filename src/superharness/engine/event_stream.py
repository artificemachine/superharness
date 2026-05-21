"""Event stream — writes structured JSONL events for lifecycle, dispatch, and discussion events.

One JSON object per line. Dashboards and external clients tail the file.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import logging
logger = logging.getLogger(__name__)


def _stream_path(project_dir: str) -> str:
    return os.path.join(project_dir, ".superharness", "events.jsonl")


def write_event(
    project_dir: str,
    event_type: str,
    **fields,
) -> None:
    """Append a JSONL event to the stream."""
    event = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        **fields,
    }
    try:
        path = _stream_path(project_dir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        logger.warning("event_stream.py unexpected error: %s", e, exc_info=True)
        pass  # best-effort — don't crash on event write failure


def read_events(project_dir: str, limit: int = 100) -> list[dict]:
    """Read the most recent events from the stream."""
    path = _stream_path(project_dir)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r") as f:
            lines = f.readlines()[-limit:]
        events = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return events
    except Exception as e:
        logger.warning("event_stream.py unexpected error: %s", e, exc_info=True)
        return []
