"""Tests for engine/model_fallback.py — Phase 3 model fallback chain."""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# _fallback_sequence
# ---------------------------------------------------------------------------

def test_fallback_sequence_standard_gives_standard_and_mini():
    from superharness.engine.model_fallback import _fallback_sequence
    seq = _fallback_sequence("claude-code", starting_tier="standard")
    assert len(seq) == 2
    assert "sonnet" in seq[0] or "claude" in seq[0]
    assert "haiku" in seq[1] or "claude" in seq[1]


def test_fallback_sequence_max_gives_all_three():
    from superharness.engine.model_fallback import _fallback_sequence
    seq = _fallback_sequence("claude-code", starting_tier="max")
    assert len(seq) == 3


def test_fallback_sequence_mini_gives_only_mini():
    from superharness.engine.model_fallback import _fallback_sequence
    seq = _fallback_sequence("claude-code", starting_tier="mini")
    assert len(seq) == 1


def test_fallback_sequence_unknown_agent_returns_empty():
    from superharness.engine.model_fallback import _fallback_sequence
    seq = _fallback_sequence("nonexistent-agent", starting_tier="standard")
    assert seq == []


# ---------------------------------------------------------------------------
# FallbackChain.chain property
# ---------------------------------------------------------------------------

def test_chain_property_reflects_sequence():
    from superharness.engine.model_fallback import FallbackChain
    fc = FallbackChain("claude-code", starting_tier="standard")
    assert len(fc.chain) == 2


# ---------------------------------------------------------------------------
# FallbackChain.run — success on first attempt
# ---------------------------------------------------------------------------

def test_run_succeeds_first_attempt():
    from superharness.engine.model_fallback import FallbackChain
    fc = FallbackChain("claude-code", starting_tier="standard")
    calls = []

    def fn(model: str) -> str:
        calls.append(model)
        return "ok"

    result = fc.run(fn)
    assert result == "ok"
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# FallbackChain.run — fallback on TimeoutError
# ---------------------------------------------------------------------------

def test_run_falls_back_on_timeout():
    from superharness.engine.model_fallback import FallbackChain
    fc = FallbackChain("claude-code", starting_tier="standard")
    calls = []

    def fn(model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise TimeoutError("too slow")
        return "recovered"

    result = fc.run(fn)
    assert result == "recovered"
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# FallbackChain.run — FallbackExhausted when all fail
# ---------------------------------------------------------------------------

def test_run_raises_fallback_exhausted_when_all_fail():
    from superharness.engine.model_fallback import FallbackChain, FallbackExhausted
    fc = FallbackChain("claude-code", starting_tier="standard")

    def fn(model: str) -> str:
        raise TimeoutError("always fails")

    with pytest.raises(FallbackExhausted) as exc_info:
        fc.run(fn)

    err = exc_info.value
    assert err.agent == "claude-code"
    assert len(err.tried) == 2


# ---------------------------------------------------------------------------
# FallbackChain.run — non-trigger exception propagates immediately
# ---------------------------------------------------------------------------

def test_run_propagates_non_trigger_exception():
    from superharness.engine.model_fallback import FallbackChain
    fc = FallbackChain("claude-code", starting_tier="standard")

    def fn(model: str) -> str:
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        fc.run(fn)


# ---------------------------------------------------------------------------
# FallbackChain — custom error_exceptions
# ---------------------------------------------------------------------------

def test_run_custom_error_exception_triggers_fallback():
    from superharness.engine.model_fallback import FallbackChain
    fc = FallbackChain(
        "claude-code",
        starting_tier="standard",
        error_exceptions=(RuntimeError,),
    )
    calls = []

    def fn(model: str) -> str:
        calls.append(model)
        if len(calls) == 1:
            raise RuntimeError("model unavailable")
        return "fallback-ok"

    result = fc.run(fn)
    assert result == "fallback-ok"


# ---------------------------------------------------------------------------
# FallbackExhausted — no models available
# ---------------------------------------------------------------------------

def test_run_raises_when_no_chain():
    from superharness.engine.model_fallback import FallbackChain, FallbackExhausted
    fc = FallbackChain("unknown-agent", starting_tier="standard")
    with pytest.raises(FallbackExhausted):
        fc.run(lambda m: m)
