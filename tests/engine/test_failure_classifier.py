"""Tests for engine.failure_classifier — RED tests for iter 1 of auto-mode-gap-plan."""
from __future__ import annotations

import pytest


@pytest.fixture
def classify():
    from superharness.engine.failure_classifier import classify
    return classify


def test_classifies_bash_unbound_variable_as_permanent_block(classify) -> None:
    """The exact bug we hit on 2026-04-27: bash 3.2 + set -u + empty array."""
    log_tail = "/path/to/delegate-to-claude.sh: line 86: CLAUDE_ARGS[@]: unbound variable"
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "permanent_block"
    assert r.retryable is False
    assert "unbound variable" in r.explain.lower() or "bash" in r.explain.lower()


def test_classifies_timeout_as_transient(classify) -> None:
    r = classify(launcher_rc=124, error_text="", log_tail="")
    assert r.category == "transient"
    assert r.retryable is True
    assert "timeout" in r.explain.lower() or "timed out" in r.explain.lower()


def test_classifies_quota_exceeded_as_surface_to_operator(classify) -> None:
    r = classify(launcher_rc=1, error_text="", log_tail="Error: rate limit exceeded for token quota")
    assert r.category == "quota"
    assert r.retryable is False
    assert "quota" in r.explain.lower() or "rate" in r.explain.lower()


def test_classifies_no_output_as_no_op(classify) -> None:
    """Agent ran successfully but produced no handoff or work artifact."""
    r = classify(launcher_rc=0, error_text="", log_tail="")
    assert r.category == "no_op"
    # No-op is not retryable: same prompt will produce same no-op
    assert r.retryable is False


def test_classifies_agent_crash_as_retry_once(classify) -> None:
    log_tail = "Traceback (most recent call last):\n  File ..., line 42, in main\nAttributeError: 'NoneType' object has no attribute 'foo'"
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "agent_crash"
    assert r.retryable is True


def test_classifies_missing_contract_task_as_permanent_block(classify) -> None:
    r = classify(launcher_rc=1, error_text="task not found in contract: feat.foo", log_tail="")
    assert r.category == "permanent_block"
    assert r.retryable is False


def test_unknown_failure_falls_back_to_unknown_class(classify) -> None:
    r = classify(launcher_rc=42, error_text="", log_tail="some weird unrecognized output")
    assert r.category == "unknown"
    # Default policy: retry unknowns once
    assert r.retryable is True


def test_classifier_returns_explanation_string_for_dashboard(classify) -> None:
    """Explain should be a non-empty human-readable string for every classification."""
    cases = [
        (1, "", "CLAUDE_ARGS[@]: unbound variable"),
        (124, "", ""),
        (1, "rate limit exceeded", ""),
        (0, "", ""),
        (1, "", "Traceback ... AttributeError: foo"),
        (1, "task not found in contract", ""),
        (42, "", "weird"),
    ]
    for rc, err, log in cases:
        r = classify(launcher_rc=rc, error_text=err, log_tail=log)
        assert isinstance(r.explain, str) and len(r.explain) > 0
