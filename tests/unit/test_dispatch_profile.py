"""Unit tests for Iter 2: DispatchProfile — role-based payload filtering."""
from __future__ import annotations

import json

import pytest

from superharness.engine.dispatch_profile import DispatchProfile


class TestDispatchProfileRoles:
    def test_worker_allows_full_payload(self):
        profile = DispatchProfile.for_role("worker")
        assert not profile.fresh_worktree
        assert profile.inherit_context
        assert profile.payload_filter is None

    def test_validator_requires_fresh_worktree(self):
        profile = DispatchProfile.for_role("validator")
        assert profile.fresh_worktree
        assert not profile.inherit_context

    def test_code_reviewer_requires_fresh_worktree(self):
        profile = DispatchProfile.for_role("code_reviewer")
        assert profile.fresh_worktree
        assert not profile.inherit_context

    def test_orchestrator_allows_full_context(self):
        profile = DispatchProfile.for_role("orchestrator")
        assert not profile.fresh_worktree
        assert profile.inherit_context
        assert profile.payload_filter is None

    def test_unknown_role_falls_back_to_worker(self):
        profile = DispatchProfile.for_role("unknown_role")
        assert profile.payload_filter is None


class TestDispatchProfilePayloadFilter:
    def test_worker_filter_passes_all_keys(self):
        profile = DispatchProfile.for_role("worker")
        payload = {"a": 1, "b": 2, "worker_session_log": "big log"}
        assert profile.filter_payload(payload) == payload

    def test_validator_filter_strips_worker_context(self):
        profile = DispatchProfile.for_role("validator")
        payload = {
            "locked_contract": {"acceptance_criteria": ["do X"]},
            "diff_since_plan_approved": "diff text",
            "handoff_report": "report",
            "worker_session_log": "should be stripped",
            "worker_context_window": "should be stripped",
        }
        filtered = profile.filter_payload(payload)
        assert "worker_session_log" not in filtered
        assert "worker_context_window" not in filtered
        assert "locked_contract" in filtered
        assert "diff_since_plan_approved" in filtered

    def test_code_reviewer_strips_handoff_report(self):
        profile = DispatchProfile.for_role("code_reviewer")
        payload = {
            "locked_contract": {},
            "diff_since_plan_approved": "diff",
            "handoff_report": "included? no",  # not in code_reviewer filter
        }
        filtered = profile.filter_payload(payload)
        assert "handoff_report" not in filtered
        assert "locked_contract" in filtered


class TestBuildReviewPayload:
    def test_build_review_payload_parses_locked_contract_json(self):
        profile = DispatchProfile.for_role("validator")
        lc = json.dumps({"acceptance_criteria": ["X"], "tdd": {}})
        payload = profile.build_review_payload(
            locked_contract=lc, diff="diff text", handoff_report="report"
        )
        assert isinstance(payload["locked_contract"], dict)
        assert payload["locked_contract"]["acceptance_criteria"] == ["X"]

    def test_build_review_payload_with_none_contract(self):
        profile = DispatchProfile.for_role("validator")
        payload = profile.build_review_payload(
            locked_contract=None, diff="diff", handoff_report=None
        )
        assert payload["locked_contract"] is None


# ── Iter 5 RED: autonomy gate consistency ─────────────────────────────────────

class TestAutonomyGateConsistency:
    """Verify normalize_autonomy preserves supervised and pipeline_check uses it."""

    def test_normalize_autonomy_preserves_supervised(self):
        """normalize_autonomy("supervised") must return "supervised", not "ai_driven"."""
        from superharness.engine.profile import normalize_autonomy
        result = normalize_autonomy("supervised")
        assert result == "supervised", (
            f"normalize_autonomy('supervised') returned {result!r}; "
            "expected 'supervised' (should not collapse to ai_driven)"
        )

    def test_pipeline_check_matches_runtime(self):
        """pipeline_check must call normalize_autonomy so aliases like 'full-auto' are accepted."""
        from superharness.engine.profile import normalize_autonomy
        import inspect
        from superharness.commands import pipeline_check as pc
        # Precondition: 'full-auto' normalizes to 'ai_driven'
        assert normalize_autonomy("full-auto") == "ai_driven"
        # pipeline_check must use normalize_autonomy — otherwise 'full-auto' passes the runtime
        # gate but fails the pipeline_check (divergence)
        src = inspect.getsource(pc)
        assert "normalize_autonomy" in src, (
            "pipeline_check must call normalize_autonomy for consistency with runtime dispatch gate"
        )
