"""Durable journal for model catalog and docs-page failures.

A failed catalog or docs-page fetch must leave a record that survives the
process, not only a line in the console. Each failure is appended as one JSON
line to the superharness state directory. If the journal itself cannot be
written, that failure is logged and reported to the caller, never raised.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from superharness.utils.paths import resolve_state_dir

logger = logging.getLogger(__name__)

JOURNAL_FILENAME = "model-catalog-failures.jsonl"


def record_catalog_failure(source: str, reason: str, *, now: datetime | None = None) -> bool:
    """Append one failure line to the journal; return True when it was written.

    Always logs the failure. Returns False, after logging, when the journal
    cannot be written (for example an unwritable state directory).
    """
    logger.warning("model catalog failure from %s: %s", source, reason)
    state_dir = resolve_state_dir()
    path = os.path.join(state_dir, JOURNAL_FILENAME)
    when = (now or datetime.now(UTC)).isoformat()
    line = json.dumps({"at": when, "source": source, "reason": reason}) + "\n"
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError as exc:
        logger.warning("could not journal model catalog failure to %s: %s", path, exc)
        return False
    return True
