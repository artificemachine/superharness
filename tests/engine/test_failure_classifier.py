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


def test_classifies_codex_chatgpt_account_model_rejection_as_auth_mismatch(classify) -> None:
    """Codex CLI rejects a model when the operator switches ChatGPT accounts.

    Must be auth_mismatch (retryable=True) so the watcher retries after the
    dispatch failure handler resets the auth cache and re-detects the account.
    Previously classified as permanent_block (retryable=False) which caused
    the watcher to never retry — the operator had to manually re-dispatch.
    """
    log_tail = (
        'ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error",'
        '"message":"The \'openai/gpt-5.3-codex\' model is not supported when using '
        'Codex with a ChatGPT account."}}'
    )
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "auth_mismatch"
    assert r.retryable is True
    assert "auth" in r.explain.lower() or "chatgpt" in r.explain.lower()


def test_classifies_gemini_model_not_found_as_permanent_block(classify) -> None:
    """gemini-cli 404 on a non-existent model (e.g. gemini-3.1-pro-preview) is
    a permanent config error — retrying with the same model will always 404."""
    log_tail = (
        "ModelNotFoundError: Requested entity was not found.\n"
        "    at classifyGoogleError (gemini-cli/bundle/chunk.js:304146:12)\n"
        "An unexpected critical error occurred:[object Object]"
    )
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "permanent_block"
    assert r.retryable is False
    assert "model" in r.explain.lower()


def test_classifies_gemini_resource_exhausted_as_quota(classify) -> None:
    """RESOURCE_EXHAUSTED is the Google API gRPC code for usage limit exceeded."""
    log_tail = "Error: RESOURCE_EXHAUSTED: Quota exceeded for quota metric 'generate_content_free_tier_requests'"
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "quota"
    assert r.retryable is False
    assert "gemini" in r.explain.lower() or "usage" in r.explain.lower() or "quota" in r.explain.lower()


def test_classifies_gemini_usage_limit_message_as_quota(classify) -> None:
    """Gemini CLI usage limit message (shown to free-tier users)."""
    log_tail = "You've reached your free tier usage limit for Gemini API."
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "quota"
    assert r.retryable is False


def test_classifies_gemini_api_key_invalid_as_auth_mismatch(classify) -> None:
    """API_KEY_INVALID from Gemini when the Google account is switched.

    This is retryable: once the user updates the GEMINI_API_KEY env var the
    next dispatch should succeed. Distinct from ModelNotFoundError (wrong model
    name in config) which is permanent.
    """
    log_tail = (
        "API error: 400 API_KEY_INVALID\n"
        "API key not valid. Please pass a valid API key."
    )
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "auth_mismatch"
    assert r.retryable is True
    assert "auth" in r.explain.lower() or "key" in r.explain.lower() or "credential" in r.explain.lower()


def test_classifies_opencode_invalid_api_key_as_auth_mismatch(classify) -> None:
    """OpenCode / DeepSeek 'Invalid API key' when the key is rotated or wrong."""
    log_tail = "Error: Invalid API key. You can find your API key at https://platform.deepseek.com/api-keys."
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "auth_mismatch"
    assert r.retryable is True


def test_classifies_opencode_rate_limit_exceeded_as_quota(classify) -> None:
    """DeepSeek / OpenCode rate_limit_exceeded (underscore form, no space)."""
    log_tail = '{"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached."}}'
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "quota"
    assert r.retryable is False


def test_classifies_insufficient_quota_as_quota(classify) -> None:
    """OpenAI-style insufficient_quota (billing hard limit)."""
    log_tail = "You exceeded your current quota, please check your plan and billing details. insufficient_quota"
    r = classify(launcher_rc=1, error_text="", log_tail=log_tail)
    assert r.category == "quota"
    assert r.retryable is False
