"""Tests for engine.summarizer.

Provider-agnostic interface for turning task context into an observation
summary. The Noop implementation is deterministic, network-free, and used
as the default so the auto-capture loop ships without any external call.
External providers (Anthropic, Gemini, OpenRouter) are designed to plug
into the same protocol but are out of scope for this iteration.
"""
from __future__ import annotations

import pytest

from superharness.engine.summarizer import (
    Summarizer,
    NoopSummarizer,
    get_summarizer,
    SummarizerError,
)


@pytest.fixture
def sample_context():
    return {
        "task_id": "feat.refactor-x",
        "phase": "report_ready",
        "title": "Refactor X",
        "outcome": "Refactored X. Removed Y. Added Z.",
        "from_agent": "claude-code",
        "to_agent": "owner",
        "created_at": "2026-05-11T10:00:00Z",
    }


def test_noop_returns_non_empty(sample_context):
    s = NoopSummarizer()
    out = s.summarize(sample_context)
    assert out
    assert isinstance(out, str)


def test_noop_is_deterministic(sample_context):
    s = NoopSummarizer()
    assert s.summarize(sample_context) == s.summarize(sample_context)


def test_noop_includes_task_id_and_outcome(sample_context):
    s = NoopSummarizer()
    out = s.summarize(sample_context)
    assert "feat.refactor-x" in out
    assert "Refactored X" in out


def test_noop_handles_missing_outcome():
    s = NoopSummarizer()
    out = s.summarize({"task_id": "t-1", "phase": "report_ready"})
    assert out
    assert "t-1" in out


def test_noop_handles_empty_context():
    s = NoopSummarizer()
    out = s.summarize({})
    assert isinstance(out, str)


def test_noop_strips_private_tags():
    s = NoopSummarizer()
    ctx = {"task_id": "t-1", "phase": "report_ready", "outcome": "ok <private>secret</private>"}
    out = s.summarize(ctx)
    assert "secret" not in out
    assert "<private>" not in out


def test_get_summarizer_default_is_noop(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_SUMMARIZER", raising=False)
    s = get_summarizer()
    assert isinstance(s, NoopSummarizer)


def test_get_summarizer_explicit_noop():
    s = get_summarizer("noop")
    assert isinstance(s, NoopSummarizer)


def test_get_summarizer_from_env(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_SUMMARIZER", "noop")
    s = get_summarizer()
    assert isinstance(s, NoopSummarizer)


def test_get_summarizer_unknown_raises(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_SUMMARIZER", raising=False)
    with pytest.raises(SummarizerError):
        get_summarizer("nonexistent-provider")


def test_summarizer_protocol_compliance():
    s = NoopSummarizer()
    assert callable(getattr(s, "summarize", None))
    assert isinstance(s, Summarizer)
