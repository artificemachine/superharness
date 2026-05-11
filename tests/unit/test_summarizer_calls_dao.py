"""Tests for engine.summarizer_calls DAO and migration v14.

Logs every summarizer invocation: provider name, model, success, and
optional token usage. Used for both cross-process rate limiting (count
recent calls per provider) and cost tracking surfaced via insights.
"""
from __future__ import annotations

import time

import pytest

from superharness.engine.db import get_connection, init_db, CURRENT_SCHEMA_VERSION
from superharness.engine import summarizer_calls


@pytest.fixture
def conn(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c = get_connection(str(project_dir))
    init_db(c, str(project_dir))
    yield c
    c.close()


def test_schema_is_at_v14(conn):
    assert CURRENT_SCHEMA_VERSION >= 14
    assert conn.execute("PRAGMA user_version").fetchone()[0] >= 14


def test_summarizer_calls_table_exists(conn):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='summarizer_calls'"
    ).fetchone()
    assert row is not None


def test_summarizer_calls_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(summarizer_calls)")}
    assert {
        "id", "provider", "model", "called_at",
        "success", "input_tokens", "output_tokens",
    }.issubset(cols)


def test_record_call_returns_id(conn):
    new_id = summarizer_calls.record_call(conn, provider="anthropic", success=True)
    assert isinstance(new_id, int) and new_id > 0


def test_record_call_persists_fields(conn):
    summarizer_calls.record_call(
        conn,
        provider="anthropic",
        success=True,
        model="claude-haiku-4-5",
        input_tokens=120,
        output_tokens=42,
    )
    row = conn.execute(
        "SELECT provider, model, success, input_tokens, output_tokens FROM summarizer_calls"
    ).fetchone()
    assert row["provider"] == "anthropic"
    assert row["model"] == "claude-haiku-4-5"
    assert row["success"] == 1
    assert row["input_tokens"] == 120
    assert row["output_tokens"] == 42


def test_record_failure(conn):
    summarizer_calls.record_call(conn, provider="anthropic", success=False)
    row = conn.execute("SELECT success FROM summarizer_calls").fetchone()
    assert row["success"] == 0


def test_count_in_window_basic(conn):
    summarizer_calls.record_call(conn, provider="anthropic", success=True)
    summarizer_calls.record_call(conn, provider="anthropic", success=True)
    summarizer_calls.record_call(conn, provider="openai", success=True)
    assert summarizer_calls.count_in_window(conn, "anthropic", window_seconds=3600) == 2
    assert summarizer_calls.count_in_window(conn, "openai", window_seconds=3600) == 1
    assert summarizer_calls.count_in_window(conn, "gemini", window_seconds=3600) == 0


def test_count_in_window_excludes_old(conn):
    # Insert with an old timestamp
    conn.execute(
        "INSERT INTO summarizer_calls (provider, called_at, success) VALUES (?, ?, ?)",
        ("anthropic", "2020-01-01T00:00:00Z", 1),
    )
    conn.commit()
    assert summarizer_calls.count_in_window(conn, "anthropic", window_seconds=3600) == 0


def test_count_in_window_only_counts_success(conn):
    summarizer_calls.record_call(conn, provider="anthropic", success=True)
    summarizer_calls.record_call(conn, provider="anthropic", success=False)
    # Default behaviour: count successes only (rate limit shouldn't penalise transient errors)
    assert summarizer_calls.count_in_window(conn, "anthropic", window_seconds=3600) == 1


def test_count_in_window_include_failures_opt_in(conn):
    summarizer_calls.record_call(conn, provider="anthropic", success=True)
    summarizer_calls.record_call(conn, provider="anthropic", success=False)
    assert summarizer_calls.count_in_window(
        conn, "anthropic", window_seconds=3600, include_failures=True
    ) == 2


def test_index_on_provider_called_at(conn):
    names = {
        r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='summarizer_calls'"
        )
    }
    assert any("provider" in n for n in names), names
