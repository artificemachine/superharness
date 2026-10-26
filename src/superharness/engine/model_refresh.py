"""Receipts of `shux models refresh`, the unattended model catalog refresh.

Every refresh run, including a skipped or failed one, appends one JSON line
to ``<state dir>/model-refresh-receipts.jsonl``. The receipt is the durable
proof that a scheduled run happened and what it did; `shux doctor` reads the
last one. Keys: ``at`` (UTC ISO time), ``outcome`` (one of ``OUTCOMES``),
``applied`` and ``skipped`` (lists of "harness tier current -> proposed"),
``errors`` (source -> reason).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from superharness.utils.paths import resolve_state_dir

RECEIPTS_FILENAME = "model-refresh-receipts.jsonl"
OUTCOMES = ("skipped", "ok", "partial", "failed")


def receipts_path() -> Path:
    return Path(resolve_state_dir()) / RECEIPTS_FILENAME


def append_receipt(
    outcome: str,
    *,
    applied: list[str],
    skipped: list[str],
    errors: dict[str, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Append one receipt line and return it; raise OSError when it cannot be written."""
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown refresh outcome: {outcome!r}")
    receipt = {
        "at": (now or datetime.now(UTC)).isoformat(),
        "outcome": outcome,
        "applied": applied,
        "skipped": skipped,
        "errors": errors,
    }
    path = receipts_path()
    os.makedirs(path.parent, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt) + "\n")
    return receipt


def last_receipt() -> dict[str, Any] | None:
    """The newest well-formed receipt, or None; malformed lines are skipped, never raised."""
    try:
        lines = receipts_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            receipt = json.loads(line)
        except ValueError:
            continue
        if isinstance(receipt, dict) and receipt.get("outcome") in OUTCOMES and "at" in receipt:
            return receipt
    return None
