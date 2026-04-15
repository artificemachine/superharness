"""Tests for superharness.engine.lifecycle — canonical workflow/status helpers."""
from __future__ import annotations

from superharness.engine.lifecycle import (
    TERMINAL_STATUSES,
    allowed_statuses_for_workflow,
    infer_workflow,
    plan_only_allowed_statuses,
)


# ── infer_workflow ───────────────────────────────────────────────────────────

def test_infer_workflow_explicit_field_wins():
    assert infer_workflow("any.id", {"workflow": "quick"}) == "quick"
    assert infer_workflow("any.id", {"workflow": "note"}) == "note"


def test_infer_workflow_normalises_case_and_whitespace():
    assert infer_workflow("any", {"workflow": "  IMPLEMENTATION  "}) == "implementation"


def test_infer_workflow_defaults_to_implementation():
    assert infer_workflow("feat.x", None) == "implementation"
    assert infer_workflow("feat.x", {}) == "implementation"


def test_infer_workflow_discussion_pattern_is_discussion():
    assert infer_workflow("discuss-abc/round-1", None) == "discussion"
    assert infer_workflow("discuss-topic/round-42", {}) == "discussion"


def test_infer_workflow_ignores_discussion_pattern_when_explicit_field_set():
    # Explicit field always wins over the id-pattern heuristic.
    assert infer_workflow("discuss-x/round-1", {"workflow": "quick"}) == "quick"


# ── allowed_statuses_for_workflow ────────────────────────────────────────────

def test_allowed_impl_excludes_todo_and_plan_proposed():
    allowed = allowed_statuses_for_workflow("implementation", for_review=False)
    assert "todo" not in allowed
    assert "plan_proposed" not in allowed
    assert "plan_approved" in allowed
    assert "in_progress" in allowed


def test_allowed_impl_includes_review_requested_when_for_review():
    assert "review_requested" in allowed_statuses_for_workflow("implementation", for_review=True)
    assert "review_requested" not in allowed_statuses_for_workflow("implementation", for_review=False)


def test_allowed_quick_includes_todo():
    assert "todo" in allowed_statuses_for_workflow("quick", for_review=False)


def test_allowed_note_excludes_report_ready():
    assert "report_ready" not in allowed_statuses_for_workflow("note", for_review=False)


def test_allowed_approval_only_pending_user_approval():
    assert allowed_statuses_for_workflow("approval", for_review=False) == {"pending_user_approval"}


def test_allowed_unknown_workflow_defaults_to_plan_approved_in_progress():
    assert allowed_statuses_for_workflow("nonsense", for_review=False) == {"plan_approved", "in_progress"}


# ── plan_only_allowed_statuses ───────────────────────────────────────────────

def test_plan_only_implementation_includes_todo_and_plan_proposed():
    allowed = plan_only_allowed_statuses("implementation")
    assert "todo" in allowed
    assert "plan_proposed" in allowed
    assert "plan_approved" in allowed  # re-dispatch after approval still valid
    assert "review_failed" in allowed  # revise plan after a failed review


def test_plan_only_noop_for_non_implementation_workflows():
    # plan_only is only meaningful for implementation — other workflows keep their normal gate.
    assert plan_only_allowed_statuses("quick") == allowed_statuses_for_workflow("quick", for_review=False)
    assert plan_only_allowed_statuses("note") == allowed_statuses_for_workflow("note", for_review=False)


# ── TERMINAL_STATUSES ────────────────────────────────────────────────────────

def test_terminal_statuses_cover_done_failed_stopped():
    assert TERMINAL_STATUSES == {"done", "failed", "stopped"}
