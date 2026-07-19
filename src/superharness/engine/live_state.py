"""Ordered, deduped, retrying write chokepoint for watcher status mirrors.

A single-worker ThreadPoolExecutor guarantees write ORDER (FIFO) regardless
of which thread calls publish(). A dedupe map skips re-issuing a write for a
key/value pair already applied (or in flight); on failure the dedupe entry
for that key is evicted so the NEXT publish (even with the identical value)
retries the underlying write. All write_fn exceptions are caught and logged
inside the worker — they never propagate back to the caller of publish().

Replaces the ad-hoc `except Exception: pass` pattern used at watcher status
mirror call sites in inbox_watch.py with one disciplined write path.

TODO (future iteration, not this one): migrate the remaining ~10
inbox_watch.py mirror sites (see grep `_sqlite_mirror_`,
`_sqlite_singleton_*`) to this chokepoint. Only the two simplest status
mirrors (`_sqlite_mirror_task_status`, `_sqlite_mirror_inbox_retry`) are
migrated in iteration 3 of docs/PLAN-steal-omnigent.md.

See docs/PLAN-steal-omnigent.md iteration 3.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

logger = logging.getLogger(__name__)

WriteFn = Callable[[str, str], None]


class LiveStateWriter:
    """Ordered, deduped, retrying single-worker write chokepoint."""

    def __init__(self, write_fn: WriteFn):
        self._write_fn = write_fn
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._lock = threading.Lock()
        self._last: dict[str, str] = {}

    def publish(self, key: str, value: str) -> None:
        """Queue a write for key/value.

        Deduped against the last-published value for this key: if unchanged,
        no new write is queued. Marking happens optimistically (before the
        write actually runs) so back-to-back synchronous publishes of the
        same value only ever queue one write, regardless of executor timing.
        """
        with self._lock:
            if self._last.get(key) == value:
                return
            self._last[key] = value
        self._executor.submit(self._apply, key, value)

    def _apply(self, key: str, value: str) -> None:
        try:
            self._write_fn(key, value)
        except Exception:
            logger.warning(
                "live_state: write failed for key=%r; dedupe entry evicted, "
                "will retry on next publish",
                key,
                exc_info=True,
            )
            with self._lock:
                if self._last.get(key) == value:
                    del self._last[key]

    def flush(self, timeout: Optional[float] = None) -> bool:
        """Block until all writes queued so far have been applied.

        Returns True if the queue drained within timeout, False on timeout.
        """
        done = threading.Event()
        self._executor.submit(done.set)
        return done.wait(timeout)


_default_writer: LiveStateWriter | None = None


def configure(write_fn: WriteFn) -> None:
    """Configure the module-level default writer."""
    global _default_writer
    _default_writer = LiveStateWriter(write_fn)


def publish(key: str, value: str) -> None:
    """Publish through the module-level default writer.

    No-op (with a warning) if configure() was never called.
    """
    if _default_writer is None:
        logger.warning("live_state.publish called before configure(); dropping key=%r", key)
        return
    _default_writer.publish(key, value)


def flush(timeout: Optional[float] = None) -> bool:
    if _default_writer is None:
        return True
    return _default_writer.flush(timeout)
