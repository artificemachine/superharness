"""Tests for the per-process rate limiter wrapping summarizers.

Bucket holds timestamps of recent calls in a 1-hour window. Exceeding
the bucket raises RateLimitExceeded. Env var
SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR overrides the registry default.
"""
from __future__ import annotations

import time

import pytest

from superharness.engine import summarizer as summarizer_mod
from superharness.engine.summarizer import (
    NoopSummarizer,
    RateLimitExceeded,
    SummarizerConfig,
    _RateLimitedSummarizer,
    _resolve_max_per_hour,
    get_summarizer,
    register_summarizer,
)


@pytest.fixture
def fake_clock(monkeypatch):
    """A controllable time source so we don't actually wait an hour."""
    state = {"now": 1_000_000.0}

    def _now():
        return state["now"]

    monkeypatch.setattr(summarizer_mod.time, "time", _now)
    return state


def test_under_budget_passes_through(fake_clock):
    s = _RateLimitedSummarizer(NoopSummarizer(), max_per_hour=3)
    out1 = s.summarize({"task_id": "t-1", "phase": "report_ready"})
    out2 = s.summarize({"task_id": "t-2", "phase": "report_ready"})
    assert out1 and out2


def test_at_budget_raises(fake_clock):
    s = _RateLimitedSummarizer(NoopSummarizer(), max_per_hour=2)
    s.summarize({"task_id": "t-1", "phase": "report_ready"})
    s.summarize({"task_id": "t-2", "phase": "report_ready"})
    with pytest.raises(RateLimitExceeded):
        s.summarize({"task_id": "t-3", "phase": "report_ready"})


def test_old_calls_expire(fake_clock):
    s = _RateLimitedSummarizer(NoopSummarizer(), max_per_hour=1)
    s.summarize({"task_id": "t-1", "phase": "report_ready"})
    fake_clock["now"] += 3601  # one second past the hour window
    # should not raise now that the old call has aged out
    s.summarize({"task_id": "t-2", "phase": "report_ready"})


def test_env_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR", "5")
    config = SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=100)
    assert _resolve_max_per_hour(config) == 5


def test_env_override_zero_disables(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR", "0")
    config = SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=100)
    assert _resolve_max_per_hour(config) is None


def test_env_override_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR", "not-a-number")
    config = SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=7)
    assert _resolve_max_per_hour(config) == 7


def test_get_summarizer_wraps_when_limit_set(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR", raising=False)
    register_summarizer(
        "_test_limited",
        SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=10),
    )
    s = get_summarizer("_test_limited")
    assert isinstance(s, _RateLimitedSummarizer)


def test_get_summarizer_does_not_wrap_noop():
    s = get_summarizer("noop")
    assert isinstance(s, NoopSummarizer)


def test_env_override_can_wrap_unlimited_provider(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR", "2")
    register_summarizer(
        "_test_unwrapped",
        SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=None),
    )
    s = get_summarizer("_test_unwrapped")
    assert isinstance(s, _RateLimitedSummarizer)


def test_capture_catches_rate_limit_error(tmp_path):
    """A rate-limited summarizer raising must not break observation_capture."""
    from superharness.engine.db import get_connection, init_db, now_iso
    from superharness.engine import observations_dao
    from superharness.engine.observation_capture import capture_observation

    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    conn = get_connection(str(project_dir))
    try:
        init_db(conn, str(project_dir))
        conn.execute(
            "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, ?, ?, ?, ?)",
            ("t-1", "x", "report_ready", 1, now_iso()),
        )
        conn.commit()

        class _Limited:
            def summarize(self, _):
                raise RateLimitExceeded("budget hit")

        obs_id = capture_observation(conn, "t-1", "report_ready", summarizer=_Limited())
        assert obs_id is None
        assert observations_dao.list_for_task(conn, "t-1") == []
    finally:
        conn.close()
