"""Iteration 1 — age-stamped recall.

Recall hits older than a threshold must carry a staleness caveat so stale
file:line claims are not asserted as live fact. Fresh hits stay clean.
"""
from __future__ import annotations

from datetime import date, timedelta

from superharness.engine import recall


def test_caveat_absent_for_fresh_hit():
    """A hit dated today produces no caveat."""
    out = recall.format_results(
        [{"date": date.today(), "agent": "a", "task_id": "t", "count": 1, "snippets": ["x"]}],
        max_fresh_days=14,
    )
    assert "days old" not in out
    assert "Verify" not in out


def test_caveat_present_for_old_hit():
    """A hit dated 30 days ago produces a caveat naming its exact age."""
    old = date.today() - timedelta(days=30)
    out = recall.format_results(
        [{"date": old, "agent": "a", "task_id": "t", "count": 1, "snippets": ["x"]}],
        max_fresh_days=14,
    )
    assert "30 days old" in out


def test_threshold_boundary():
    """At the threshold: no caveat. One day past it: caveat."""
    assert recall._freshness_caveat(14, 14) == ""
    assert recall._freshness_caveat(15, 14) != ""
    assert "15 days old" in recall._freshness_caveat(15, 14)


def test_zero_threshold_flags_every_dated_hit():
    """--max-fresh-days 0 makes any dated hit (age >= 1) show a caveat."""
    assert recall._freshness_caveat(1, 0) != ""


def test_undated_hit_no_crash():
    """A hit with no parseable date produces no caveat and no exception."""
    out = recall.format_results(
        [{"date": None, "agent": "a", "task_id": "t", "count": 1, "snippets": ["x"]}],
        max_fresh_days=14,
    )
    assert "days old" not in out
    assert recall._freshness_caveat(None, 14) == ""


def test_resolve_max_fresh_days_env(monkeypatch):
    """Env override is honored when no explicit CLI value is given."""
    monkeypatch.setenv("SHUX_RECALL_FRESH_DAYS", "3")
    assert recall._resolve_max_fresh_days(None) == 3
    # Explicit CLI value wins over env.
    assert recall._resolve_max_fresh_days(30) == 30
