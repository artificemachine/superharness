"""Tests for ClaudeCodeSummarizer.

Subprocesses the `claude` CLI in non-interactive print mode (`-p`).
Reuses whatever authentication Claude Code is configured with (Claude
Max OAuth or ANTHROPIC_API_KEY) so the operator does not need a
separate API key in env.

Same shape as OpenCodeSummarizer; both inherit from the shared
_CLISummarizer base extracted in this iteration.
"""
from __future__ import annotations

import pytest

from superharness.engine import summarizer_providers as providers
from superharness.engine.summarizer import SummarizerError, get_summarizer


@pytest.fixture
def sample_context():
    return {
        "task_id": "feat.x",
        "phase": "report_ready",
        "title": "Implement x",
        "outcome": "Did x.",
        "from_agent": "claude-code",
    }


def test_construction_requires_binary(monkeypatch):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: None)
    with pytest.raises(SummarizerError):
        providers.ClaudeCodeSummarizer()


def test_round_trip(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    captured: dict = {}

    class _Result:
        returncode = 0
        stdout = "Claude says hi"
        stderr = ""

    def _run(args, **kw):
        captured["args"] = args
        return _Result()

    monkeypatch.setattr(providers.subprocess, "run", _run)
    s = providers.ClaudeCodeSummarizer()
    out = s.summarize(sample_context)
    assert out == "Claude says hi"
    # Default invocation includes -p
    assert "-p" in captured["args"]
    assert captured["args"][0] == "claude"


def test_strips_ansi(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    class _Result:
        returncode = 0
        stdout = "\x1b[32mclaude reply\x1b[0m"
        stderr = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = providers.ClaudeCodeSummarizer()
    out = s.summarize(sample_context)
    assert "\x1b" not in out
    assert "claude reply" in out


def test_strips_private_tags(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    class _Result:
        returncode = 0
        stdout = "ok <private>leak</private> rest"
        stderr = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = providers.ClaudeCodeSummarizer()
    out = s.summarize(sample_context)
    assert "leak" not in out
    assert "<private>" not in out


def test_non_zero_exit_raises(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    class _Result:
        returncode = 2
        stdout = ""
        stderr = "permission denied"

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = providers.ClaudeCodeSummarizer()
    with pytest.raises(SummarizerError):
        s.summarize(sample_context)


def test_timeout_raises(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    def _raise(*a, **kw):
        raise providers.subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(providers.subprocess, "run", _raise)
    s = providers.ClaudeCodeSummarizer()
    with pytest.raises(SummarizerError):
        s.summarize(sample_context)


def test_model_flag_passed(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    captured: dict = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _run(args, **kw):
        captured["args"] = args
        return _Result()

    monkeypatch.setattr(providers.subprocess, "run", _run)
    s = providers.ClaudeCodeSummarizer(model="claude-opus-4-7")
    s.summarize(sample_context)
    assert "--model" in captured["args"]
    assert "claude-opus-4-7" in captured["args"]


def test_registered_under_claude_code(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    class _Result:
        returncode = 0
        stdout = "registered"
        stderr = ""

    monkeypatch.setattr(providers.subprocess, "run", lambda *a, **kw: _Result())
    s = get_summarizer("claude-code")
    # Wrapped by rate limiter; check it still summarises
    assert s.summarize(sample_context) == "registered"


def test_custom_subcommand_via_init_kwargs(monkeypatch, sample_context):
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/claude")

    captured: dict = {}

    class _Result:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def _run(args, **kw):
        captured["args"] = args
        return _Result()

    monkeypatch.setattr(providers.subprocess, "run", _run)
    s = providers.ClaudeCodeSummarizer(subcommand=("--print", "--no-color"))
    s.summarize(sample_context)
    assert "--print" in captured["args"]
    assert "--no-color" in captured["args"]


def test_opencode_still_works_after_refactor(monkeypatch, sample_context):
    """Regression: OpenCodeSummarizer behaviour must be unchanged after _CLISummarizer extraction."""
    monkeypatch.setattr(providers.shutil, "which", lambda _name: "/usr/bin/opencode")

    captured: dict = {}

    class _Result:
        returncode = 0
        stdout = "opencode still ok"
        stderr = ""

    def _run(args, **kw):
        captured["args"] = args
        return _Result()

    monkeypatch.setattr(providers.subprocess, "run", _run)
    s = providers.OpenCodeSummarizer()
    assert s.summarize(sample_context) == "opencode still ok"
    assert captured["args"][0] == "opencode"
    assert "run" in captured["args"]
