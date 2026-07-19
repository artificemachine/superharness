"""Typed telemetry events: task transitions and dispatch lifecycle, written
to the `events` SQLite table (migration v31) by a background emitter whose
failures never disturb business logic.

Distinct from (and additive to) engine/event_stream.py, which appends
free-form JSONL events to `.superharness/events.jsonl` for dashboard
tailing. This module is the typed, queryable SQLite counterpart consumed by
later iterations (transcript tailing / dual watchdog deadline checks).

Call-site contract, deliberately conservative to avoid spawning background
threads across every project a test or CLI command ever touches: emit() is a
silent (debug-logged) no-op until configure(project_dir) has been called for
that process. Callers that want events recorded (the watcher cycle,
directed tests) call configure() once; callers that don't care (most of the
existing test suite, which drives state_writer.set_task_status heavily)
never spawn an emitter thread at all.

See docs/PLAN-steal-omnigent.md iteration 4.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional, Union

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskTransition:
    task_id: str
    from_status: str
    to_status: str

    @property
    def kind(self) -> str:
        return "task_transition"


@dataclass(frozen=True)
class DispatchStarted:
    task_id: str
    agent: str

    @property
    def kind(self) -> str:
        return "dispatch_started"


@dataclass(frozen=True)
class DispatchFinished:
    task_id: str
    agent: str
    duration_s: float
    exit_code: int

    @property
    def kind(self) -> str:
        return "dispatch_finished"


Event = Union[TaskTransition, DispatchStarted, DispatchFinished]


@dataclass(frozen=True)
class _FlushMarker:
    done: threading.Event


class _Emitter:
    """Background queue-drain thread. One instance per configured project."""

    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self._queue: "queue.Queue[object]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def emit(self, event: Event) -> None:
        self._queue.put(event)

    def flush(self, timeout: Optional[float] = None) -> bool:
        done = threading.Event()
        self._queue.put(_FlushMarker(done))
        return done.wait(timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if isinstance(item, _FlushMarker):
                item.done.set()
                continue
            self._write_one(item)

    def _write_one(self, event: Event) -> None:
        try:
            from superharness.engine.db import get_connection, init_db

            conn = get_connection(self.project_dir)
            try:
                init_db(conn)
                now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                payload = json.dumps(asdict(event), sort_keys=True)
                task_id = getattr(event, "task_id", None)
                conn.execute(
                    "INSERT INTO events (ts, kind, task_id, payload_json) VALUES (?, ?, ?, ?)",
                    (now, event.kind, task_id, payload),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.warning(
                "events: emit failed for kind=%r task_id=%r",
                getattr(event, "kind", "?"),
                getattr(event, "task_id", "?"),
                exc_info=True,
            )


_emitter: _Emitter | None = None


def configure(project_dir: str) -> None:
    """Configure the module-level emitter for project_dir.

    Idempotent for repeat calls with the same project_dir (keeps the
    existing background thread instead of spawning a new one each time).
    """
    global _emitter
    if _emitter is not None and _emitter.project_dir == project_dir:
        return
    _emitter = _Emitter(project_dir)


def emit(event: Event) -> None:
    """Queue event for background write. Silent no-op if unconfigured."""
    if _emitter is None:
        logger.debug("events.emit called before configure(); dropping %r", event)
        return
    _emitter.emit(event)


def flush(timeout: Optional[float] = None) -> bool:
    if _emitter is None:
        return True
    return _emitter.flush(timeout)
