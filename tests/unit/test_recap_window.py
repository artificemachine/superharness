"""Tests for recap window timezone handling (Iteration 1, fix/queued-defects-2026-09-25).

Defect: `_parse_iso` returns naive datetimes for offset-less strings, and
`_within_window` then compares them against a timezone-aware cutoff
(datetime.now(timezone.utc) - timedelta(...)), raising:
    TypeError: can't compare offset-naive and offset-aware datetimes
Contract: naive timestamps are interpreted as UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from superharness.commands.recap import _within_window


def _cutoff() -> datetime:
    # Explicit, timezone-aware cutoff 6h in the past — tests are relative to
    # it, so they are never time-of-day flaky.
    return datetime.now(timezone.utc) - timedelta(hours=6)


def test_naive_timestamp_within_window_counts() -> None:
    cutoff = _cutoff()
    # Naive (no offset) timestamp 1h after the cutoff -> inside the window.
    naive_inside = (cutoff + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert _within_window(naive_inside, cutoff) is True


def test_naive_timestamp_outside_window_excluded() -> None:
    cutoff = _cutoff()
    # Naive timestamp 1h BEFORE the cutoff -> outside the window, no exception.
    naive_outside = (cutoff - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    assert _within_window(naive_outside, cutoff) is False


def test_aware_timestamp_still_counts() -> None:
    cutoff = _cutoff()
    # Same instant rendered aware (Z-suffixed) and naive: both must be judged
    # identically against the same cutoff (no double-shift).
    instant_inside = cutoff + timedelta(hours=2)
    aware = instant_inside.isoformat().replace("+00:00", "Z")
    naive = instant_inside.replace(tzinfo=None).isoformat()
    aware_result = _within_window(aware, cutoff)
    naive_result = _within_window(naive, cutoff)
    assert aware_result is True
    assert aware_result == naive_result
