"""DAO for summarizer_calls.

Logs every summarizer invocation. Powers two consumers:

1. Cross-process rate limiting: count successful calls per provider in
   a rolling window, compare against the configured budget. The
   in-memory bucket in `_RateLimitedSummarizer` works inside a single
   process; the SQLite-backed variant uses this DAO so multiple
   `shux` processes against the same project share one budget.

2. Cost tracking: input/output token counts captured from provider
   responses feed `shux insights` for per-provider spend roll-ups.

Defaults to "successes only" when counting for rate limit purposes so
that transient transport failures do not eat into the budget. Callers
that want a full audit count pass `include_failures=True`.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from superharness.engine.db import now_iso


def record_call(
    conn: sqlite3.Connection,
    *,
    provider: str,
    success: bool,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> int:
    """Insert a summarizer call record. Returns the new row id."""
    cur = conn.execute(
        """
        INSERT INTO summarizer_calls
            (provider, model, called_at, success, input_tokens, output_tokens)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (provider, model, now_iso(), 1 if success else 0, input_tokens, output_tokens),
    )
    conn.commit()
    return int(cur.lastrowid)


def count_in_window(
    conn: sqlite3.Connection,
    provider: str,
    *,
    window_seconds: int,
    include_failures: bool = False,
) -> int:
    """Count calls for a provider within the last window_seconds.

    Rate-limit consumers leave `include_failures=False` so transient
    transport errors don't burn the budget. Audit consumers pass True.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    cutoff_iso = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
    if include_failures:
        sql = (
            "SELECT COUNT(*) AS n FROM summarizer_calls "
            "WHERE provider = ? AND called_at >= ?"
        )
        args: tuple[Any, ...] = (provider, cutoff_iso)
    else:
        sql = (
            "SELECT COUNT(*) AS n FROM summarizer_calls "
            "WHERE provider = ? AND called_at >= ? AND success = 1"
        )
        args = (provider, cutoff_iso)
    return int(conn.execute(sql, args).fetchone()["n"])
