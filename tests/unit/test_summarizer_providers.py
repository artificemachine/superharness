"""Tests for external summarizer providers.

Each provider is tested with a mocked HTTP transport (or subprocess for
OpenCode). No real network calls. Construction failures (missing
credentials, missing binary) are also covered.

The HTTP helper `_http_post_json` is monkey-patched on the providers
module so a single fake covers Anthropic, Gemini, OpenAI, and
OpenRouter. Each test asserts the parsed text round-trips and that
private tags get stripped.
"""
from __future__ import annotations

import pytest

from superharness.engine import summarizer_providers as providers
from superharness.engine.summarizer import (
    SummarizerError,
    get_summarizer,
    list_summarizers,
)


@pytest.fixture
def sample_context():
    return {
        "task_id": "feat.x",
        "phase": "report_ready",
        "title": "Implement x",
        "outcome": "Did x.",
        "from_agent": "claude-code",
    }


def _install_anthropic_fake(monkeypatch, text="anthropic summary"):
    def fake(url, body, headers, timeout=30):
        assert url == providers.AnthropicSummarizer.API_URL
        return {"content": [{"text": text}]}
    monkeypatch.setattr(providers, "_http_post_json", fake)


def _install_gemini_fake(monkeypatch, text="gemini summary"):
    def fake(url, body, headers, timeout=30):
        assert "generativelanguage.googleapis.com" in url
        return {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    monkeypatch.setattr(providers, "_http_post_json", fake)


def _install_chat_fake(monkeypatch, text="chat summary"):
    def fake(url, body, headers, timeout=30):
        return {"choices": [{"message": {"content": text}}]}
    monkeypatch.setattr(providers, "_http_post_json", fake)


# ---------------------------------------------------------------------------
# Registry presence
# ---------------------------------------------------------------------------

def test_registry_lists_all_external_providers():
    names = list_summarizers()
    for n in ("noop", "anthropic", "gemini", "openai", "openrouter", "opencode"):
        assert n in names


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

def test_anthropic_construction_requires_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SummarizerError):
        providers.AnthropicSummarizer()


def test_anthropic_round_trips(monkeypatch, sample_context):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    _install_anthropic_fake(monkeypatch, text="ok")
    s = providers.AnthropicSummarizer()
    assert s.summarize(sample_context) == "ok"


def test_anthropic_strips_private_tags(monkeypatch, sample_context):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    _install_anthropic_fake(monkeypatch, text="ok <private>leak</private> rest")
    s = providers.AnthropicSummarizer()
    out = s.summarize(sample_context)
    assert "leak" not in out


def test_anthropic_via_registry(monkeypatch, sample_context):
    monkeypatch.delenv("SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
    _install_anthropic_fake(monkeypatch, text="ok")
    s = get_summarizer("anthropic")
    assert s.summarize(sample_context) == "ok"


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def test_gemini_construction_requires_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(SummarizerError):
        providers.GeminiSummarizer()


def test_gemini_uses_google_api_key_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "g-fake")
    s = providers.GeminiSummarizer()
    assert s.api_key == "g-fake"


def test_gemini_round_trips(monkeypatch, sample_context):
    monkeypatch.setenv("GEMINI_API_KEY", "g-fake")
    _install_gemini_fake(monkeypatch, text="gemini ok")
    s = providers.GeminiSummarizer()
    assert s.summarize(sample_context) == "gemini ok"


def test_gemini_handles_empty_candidates(monkeypatch, sample_context):
    monkeypatch.setenv("GEMINI_API_KEY", "g-fake")
    monkeypatch.setattr(providers, "_http_post_json", lambda *a, **kw: {"candidates": []})
    s = providers.GeminiSummarizer()
    assert s.summarize(sample_context) == ""


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

def test_openai_construction_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SummarizerError):
        providers.OpenAISummarizer()


def test_openai_round_trips(monkeypatch, sample_context):
    monkeypatch.setenv("OPENAI_API_KEY", "oa-fake")
    _install_chat_fake(monkeypatch, text="openai ok")
    s = providers.OpenAISummarizer()
    assert s.summarize(sample_context) == "openai ok"


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------

def test_openrouter_construction_requires_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(SummarizerError):
        providers.OpenRouterSummarizer()


def test_openrouter_round_trips(monkeypatch, sample_context):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-fake")
    _install_chat_fake(monkeypatch, text="or ok")
    s = providers.OpenRouterSummarizer()
    assert s.summarize(sample_context) == "or ok"


# ---------------------------------------------------------------------------
# OpenCode (subprocess)
# ---------------------------------------------------------------------------

def test_opencode_construction_requires_binary(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: None)
    with pytest.raises(SummarizerError):
        providers.OpenCodeSummarizer()


def test_opencode_round_trips(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/opencode")

    class _Result:
        returncode = 0
        stdout = "opencode summary text"
        stderr = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = providers.OpenCodeSummarizer()
    assert s.summarize(sample_context) == "opencode summary text"


def test_opencode_strips_ansi(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/opencode")

    class _Result:
        returncode = 0
        stdout = "\x1b[31msummary\x1b[0m"
        stderr = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = providers.OpenCodeSummarizer()
    out = s.summarize(sample_context)
    assert "\x1b" not in out
    assert "summary" in out


def test_opencode_non_zero_exit_raises(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/opencode")

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = providers.OpenCodeSummarizer()
    with pytest.raises(SummarizerError):
        s.summarize(sample_context)


def test_opencode_timeout_raises(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/opencode")

    def _raise(*a, **kw):
        raise providers.subprocess.TimeoutExpired(cmd="opencode", timeout=1)

    monkeypatch.setattr(providers.subprocess, "run", _raise)
    s = providers.OpenCodeSummarizer()
    with pytest.raises(SummarizerError):
        s.summarize(sample_context)


# ---------------------------------------------------------------------------
# get_summarizer surfaces SummarizerError on missing credentials
# ---------------------------------------------------------------------------

def test_get_summarizer_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SUPERHARNESS_SUMMARIZER", raising=False)
    with pytest.raises(SummarizerError):
        get_summarizer("anthropic")
