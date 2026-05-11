"""Tests that HTTP providers extract token usage from API responses.

Each provider sets `self.last_usage` after a successful summarize.
The SQLite-backed rate limiter reads this attribute and passes the
counts into `summarizer_calls.record_call`, so per-provider spend
shows up in `shux insights`.

CLI providers (opencode, claude-code) do not have token info in
stdout; their `last_usage` stays empty and the rate limiter records
NULL token columns.
"""
from __future__ import annotations

import pytest

from superharness.engine import summarizer_providers as providers
from superharness.engine.db import get_connection, init_db
from superharness.engine import summarizer_calls
from superharness.engine.summarizer import _SQLiteRateLimitedSummarizer


@pytest.fixture
def project_dir(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    c = get_connection(str(p))
    try:
        init_db(c, str(p))
    finally:
        c.close()
    return str(p)


@pytest.fixture
def sample_context():
    return {"task_id": "feat.x", "phase": "report_ready", "outcome": "did x"}


def test_anthropic_extracts_usage(monkeypatch, sample_context):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setattr(
        providers,
        "_http_post_json",
        lambda *a, **kw: {
            "content": [{"text": "ok"}],
            "usage": {"input_tokens": 123, "output_tokens": 45},
        },
    )
    s = providers.AnthropicSummarizer()
    s.summarize(sample_context)
    assert s.last_usage == {"model": s.model, "input_tokens": 123, "output_tokens": 45}


def test_gemini_extracts_usage(monkeypatch, sample_context):
    monkeypatch.setenv("GEMINI_API_KEY", "g-fake")
    monkeypatch.setattr(
        providers,
        "_http_post_json",
        lambda *a, **kw: {
            "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
            "usageMetadata": {"promptTokenCount": 77, "candidatesTokenCount": 12},
        },
    )
    s = providers.GeminiSummarizer()
    s.summarize(sample_context)
    assert s.last_usage["input_tokens"] == 77
    assert s.last_usage["output_tokens"] == 12


def test_openai_extracts_usage(monkeypatch, sample_context):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-fake")
    monkeypatch.setattr(
        providers,
        "_http_post_json",
        lambda *a, **kw: {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 200, "completion_tokens": 80},
        },
    )
    s = providers.OpenAISummarizer()
    s.summarize(sample_context)
    assert s.last_usage["input_tokens"] == 200
    assert s.last_usage["output_tokens"] == 80


def test_openrouter_extracts_usage(monkeypatch, sample_context):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake")
    monkeypatch.setattr(
        providers,
        "_http_post_json",
        lambda *a, **kw: {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 90, "completion_tokens": 30},
        },
    )
    s = providers.OpenRouterSummarizer()
    s.summarize(sample_context)
    assert s.last_usage["input_tokens"] == 90
    assert s.last_usage["output_tokens"] == 30


def test_missing_usage_defaults_to_none(monkeypatch, sample_context):
    """If the provider response is missing the usage block, last_usage
    has None tokens (recorded as NULL in summarizer_calls)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setattr(
        providers,
        "_http_post_json",
        lambda *a, **kw: {"content": [{"text": "ok"}]},  # no "usage" key
    )
    s = providers.AnthropicSummarizer()
    s.summarize(sample_context)
    assert s.last_usage["input_tokens"] is None
    assert s.last_usage["output_tokens"] is None


def test_sqlite_limiter_records_tokens_from_inner(monkeypatch, project_dir, sample_context):
    """Round-trip: provider sets last_usage, limiter logs into summarizer_calls."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    monkeypatch.setattr(
        providers,
        "_http_post_json",
        lambda *a, **kw: {
            "content": [{"text": "ok"}],
            "usage": {"input_tokens": 150, "output_tokens": 50},
        },
    )
    inner = providers.AnthropicSummarizer()
    s = _SQLiteRateLimitedSummarizer(
        inner, max_per_hour=10, project_dir=project_dir, provider_name="anthropic"
    )
    s.summarize(sample_context)

    conn = get_connection(project_dir)
    try:
        row = conn.execute(
            "SELECT provider, model, input_tokens, output_tokens, success FROM summarizer_calls"
        ).fetchone()
    finally:
        conn.close()
    assert row["provider"] == "anthropic"
    assert row["model"] == inner.model
    assert row["input_tokens"] == 150
    assert row["output_tokens"] == 50
    assert row["success"] == 1


def test_cli_provider_logs_null_tokens(project_dir, monkeypatch, sample_context):
    """CLI providers do not set last_usage; the limiter records NULL token columns."""
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/opencode")

    class _Result:
        returncode = 0
        stdout = "summary text"
        stderr = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    inner = providers.OpenCodeSummarizer()
    s = _SQLiteRateLimitedSummarizer(
        inner, max_per_hour=10, project_dir=project_dir, provider_name="opencode"
    )
    s.summarize(sample_context)

    conn = get_connection(project_dir)
    try:
        row = conn.execute(
            "SELECT input_tokens, output_tokens, success FROM summarizer_calls"
        ).fetchone()
    finally:
        conn.close()
    assert row["input_tokens"] is None
    assert row["output_tokens"] is None
    assert row["success"] == 1
