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

See docs/PLAN-adopt-omnigent.md iteration 4.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import queue
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional, Union, get_type_hints

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

# The three classes above are the core kinds; other modules may define their
# own frozen dataclass events (e.g. engine/transcript_tail.TranscriptProgress)
# and emit them here. The boundary is therefore structural, not nominal: a
# frozen dataclass instance exposing a non-empty str `kind` and a `task_id`.
_EVENT_TYPES: tuple[type, ...] = (TaskTransition, DispatchStarted, DispatchFinished)


def _is_event_shaped(event: object) -> bool:
    if isinstance(event, type) or not dataclasses.is_dataclass(event):
        return False
    if not getattr(type(event), "__dataclass_params__").frozen:
        return False
    kind = getattr(event, "kind", None)
    return isinstance(kind, str) and kind != "" and hasattr(event, "task_id")


def validate_event(event: object) -> None:
    """Raise synchronously if `event` is not a well-formed Event.

    - TypeError: `event` is not a frozen dataclass with a str `kind` and a
      `task_id`, or a field holds a value of the wrong type (an int is
      accepted where a float is declared).
    - ValueError: `task_id` is present but empty.

    Called as the first step of emit(), before anything is queued for the
    background writer, so malformed payloads never reach _write_one() (and
    are unaffected by whether that writer's DB call succeeds or fails).
    """
    if not _is_event_shaped(event):
        raise TypeError(
            "events.emit() expects a frozen dataclass with str `kind` and "
            f"`task_id` (e.g. {[t.__name__ for t in _EVENT_TYPES]}), "
            f"got {type(event).__name__}"
        )

    hints = get_type_hints(type(event))
    for field in dataclasses.fields(event):
        expected = hints.get(field.name)
        if expected is None:
            continue
        value = getattr(event, field.name)
        if expected is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, expected) and not (
                expected is int and isinstance(value, bool)
            )
        if not ok:
            raise TypeError(
                f"{type(event).__name__}.{field.name} expected "
                f"{expected.__name__}, got {type(value).__name__}"
            )

    task_id = getattr(event, "task_id", None)
    if task_id == "":
        raise ValueError(f"{type(event).__name__}.task_id must not be empty")


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
    """Validate then queue event for background write.

    Validation (validate_event) runs synchronously and raises TypeError /
    ValueError on a malformed payload, before anything is queued -- even if
    configure() was never called. Once validated, queuing is a silent
    no-op if unconfigured; a DB failure during the background write is
    warn-only (see _write_one).
    """
    validate_event(event)
    if _emitter is None:
        logger.debug("events.emit called before configure(); dropping %r", event)
        return
    _emitter.emit(event)


def flush(timeout: Optional[float] = None) -> bool:
    if _emitter is None:
        return True
    return _emitter.flush(timeout)
