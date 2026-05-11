"""Opt-in smoke tests against real provider APIs.

Gated by RUN_PROVIDER_SMOKE=1 and per-provider credentials. CI never
runs this. Use locally to verify that a configured provider actually
returns a non-empty summary.

Each test:
- Skips unless the gate env var is set.
- Skips unless that provider's API key is present.
- Hits the real endpoint with a tiny fixture context.
- Asserts the response is a non-empty string.

These tests cost a few cents at most per run if executed against all
providers. The OpenCode smoke test also skips when the `opencode`
binary is not on PATH.
"""
from __future__ import annotations

import os
import shutil

import pytest

from superharness.engine.summarizer import get_summarizer


_GATE = "RUN_PROVIDER_SMOKE"


def _skip_unless_gate():
    if not os.environ.get(_GATE):
        pytest.skip(f"set {_GATE}=1 to run provider smoke tests")


@pytest.fixture
def sample_context():
    return {
        "task_id": "smoke-test",
        "phase": "report_ready",
        "title": "Smoke test the summarizer",
        "outcome": "Verified that the provider returns a non-empty response.",
        "from_agent": "claude-code",
    }


def _smoke(provider_name: str, key_env: str, context: dict) -> None:
    _skip_unless_gate()
    if not os.environ.get(key_env):
        pytest.skip(f"{key_env} not set; skipping {provider_name} smoke")
    s = get_summarizer(provider_name)
    out = s.summarize(context)
    assert isinstance(out, str)
    assert out.strip(), f"{provider_name} returned empty"


def test_anthropic_smoke(sample_context):
    _smoke("anthropic", "ANTHROPIC_API_KEY", sample_context)


def test_gemini_smoke(sample_context):
    _skip_unless_gate()
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")):
        pytest.skip("GEMINI_API_KEY/GOOGLE_API_KEY not set; skipping gemini smoke")
    s = get_summarizer("gemini")
    out = s.summarize(sample_context)
    assert isinstance(out, str) and out.strip()


def test_openai_smoke(sample_context):
    _smoke("openai", "OPENAI_API_KEY", sample_context)


def test_openrouter_smoke(sample_context):
    _smoke("openrouter", "OPENROUTER_API_KEY", sample_context)


def test_opencode_smoke(sample_context):
    _skip_unless_gate()
    if not shutil.which("opencode"):
        pytest.skip("opencode binary not on PATH; skipping opencode smoke")
    s = get_summarizer("opencode")
    out = s.summarize(sample_context)
    assert isinstance(out, str) and out.strip()


def test_claude_code_smoke(sample_context):
    _skip_unless_gate()
    if not shutil.which("claude"):
        pytest.skip("claude binary not on PATH; skipping claude-code smoke")
    s = get_summarizer("claude-code")
    out = s.summarize(sample_context)
    assert isinstance(out, str) and out.strip()
