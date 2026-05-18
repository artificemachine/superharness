"""Tests for the SQLite-backed cross-process rate limiter.

When `get_summarizer` is called with `project_dir`, the returned
wrapper consults summarizer_calls instead of an in-memory deque, so
multiple processes share a budget. Every call (success or transport
failure) is logged. Budget exhaustion raises RateLimitExceeded.
DAO faults degrade gracefully (limiter allows the call rather than
blocking transitions).
"""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import summarizer_calls
from superharness.engine.summarizer import (
    NoopSummarizer,
    RateLimitExceeded,
    SummarizerConfig,
    _SQLiteRateLimitedSummarizer,
    get_summarizer,
    register_summarizer,
)


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "sh_state"))
    p = tmp_path / "proj"
    (p / ".superharness").mkdir(parents=True)
    c = get_connection(str(p))
    try:
        init_db(c, str(p))
    finally:
        c.close()
    return str(p)


def test_sqlite_limiter_logs_success(project_dir):
    s = _SQLiteRateLimitedSummarizer(
        NoopSummarizer(), max_per_hour=5, project_dir=project_dir, provider_name="noop"
    )
    s.summarize({"task_id": "t-1", "phase": "report_ready"})

    conn = get_connection(project_dir)
    try:
        assert summarizer_calls.count_in_window(conn, "noop", window_seconds=3600) == 1
    finally:
        conn.close()


def test_sqlite_limiter_blocks_when_over_budget(project_dir):
    s = _SQLiteRateLimitedSummarizer(
        NoopSummarizer(), max_per_hour=2, project_dir=project_dir, provider_name="noop"
    )
    s.summarize({"task_id": "t-1", "phase": "report_ready"})
    s.summarize({"task_id": "t-2", "phase": "report_ready"})
    with pytest.raises(RateLimitExceeded):
        s.summarize({"task_id": "t-3", "phase": "report_ready"})


def test_sqlite_limiter_two_instances_share_budget(project_dir):
    """Different summarizer instances pointed at the same DB share one bucket."""
    a = _SQLiteRateLimitedSummarizer(
        NoopSummarizer(), max_per_hour=2, project_dir=project_dir, provider_name="noop"
    )
    b = _SQLiteRateLimitedSummarizer(
        NoopSummarizer(), max_per_hour=2, project_dir=project_dir, provider_name="noop"
    )
    a.summarize({"task_id": "t-1", "phase": "report_ready"})
    b.summarize({"task_id": "t-2", "phase": "report_ready"})
    with pytest.raises(RateLimitExceeded):
        a.summarize({"task_id": "t-3", "phase": "report_ready"})


def test_sqlite_limiter_logs_failure_without_consuming_budget(project_dir):
    class _Boom:
        def summarize(self, _):
            raise RuntimeError("transport down")

    s = _SQLiteRateLimitedSummarizer(
        _Boom(), max_per_hour=2, project_dir=project_dir, provider_name="boom"
    )
    for _ in range(5):
        with pytest.raises(RuntimeError):
            s.summarize({"task_id": "x", "phase": "report_ready"})

    conn = get_connection(project_dir)
    try:
        successes = summarizer_calls.count_in_window(conn, "boom", window_seconds=3600)
        total = summarizer_calls.count_in_window(
            conn, "boom", window_seconds=3600, include_failures=True
        )
    finally:
        conn.close()
    assert successes == 0
    assert total == 5


def test_get_summarizer_with_project_dir_returns_sqlite_wrapper(project_dir):
    register_summarizer(
        "_test_sqlite",
        SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=4),
    )
    s = get_summarizer("_test_sqlite", project_dir=project_dir)
    assert isinstance(s, _SQLiteRateLimitedSummarizer)


def test_get_summarizer_without_project_dir_stays_in_memory():
    register_summarizer(
        "_test_inmem",
        SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=4),
    )
    s = get_summarizer("_test_inmem")
    # Not the SQLite variant
    assert not isinstance(s, _SQLiteRateLimitedSummarizer)


def test_sqlite_limiter_dao_failure_does_not_block(project_dir, monkeypatch, tmp_path):
    """If the DAO is broken, the limiter must not raise on the budget check."""
    # Redirect XDG state dir so the bad-path hash doesn't contaminate real FS.
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(tmp_path / "sh_state_broken"))
    s = _SQLiteRateLimitedSummarizer(
        NoopSummarizer(), max_per_hour=1, project_dir="/nonexistent/path/xyz",
        provider_name="noop",
    )
    # Budget check on a bad path swallows the error; call proceeds.
    out = s.summarize({"task_id": "t-1", "phase": "report_ready"})
    assert out
