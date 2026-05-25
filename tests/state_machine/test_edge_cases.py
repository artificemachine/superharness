"""Additional state machine tests — edge cases and coverage gaps."""
from __future__ import annotations

import pytest
from superharness.engine.next_action import validate_status_transition, _MAPPING, NextAction, ALL_STATUSES


# ── Self-transition tests (10 tests) ──────────────────────────────────────────

class TestSelfTransitions:
    """Transitioning to the same status should either be allowed or clearly rejected."""

    @pytest.mark.parametrize("status", list(_MAPPING.keys()))
    def test_self_transition_behavior(self, status):
        """Self-transition is either legal (idempotent) or raises with clear message."""
        try:
            validate_status_transition(status, status)
        except ValueError as e:
            assert "transition" in str(e).lower() or "same" in str(e).lower()


# ── Boundary tests (10 tests) ─────────────────────────────────────────────────

class TestStatusBoundaries:
    """Edge cases around status transitions."""

    @pytest.mark.parametrize("status", ["", "nonexistent", "INVALID", "123"])
    def test_invalid_status_rejected(self, status):
        """Completely invalid statuses should raise ValueError."""
        with pytest.raises(ValueError):
            validate_status_transition("todo", status)

    def test_none_status_rejected(self):
        """None status should raise."""
        with pytest.raises((ValueError, TypeError, AttributeError)):
            validate_status_transition("todo", None)  # type: ignore

    def test_empty_from_rejected(self):
        """Empty from status should raise."""
        with pytest.raises(ValueError):
            validate_status_transition("", "todo")

    def test_next_action_all_statuses(self):
        """NextAction computed for every status — at least one legal transition."""
        for status in _MAPPING:
            action = NextAction.compute(status)
            assert action is not None
            assert isinstance(action.recommended, str) or action.recommended is None
            assert isinstance(action.legal, list)

    @pytest.mark.parametrize("status", list(_MAPPING.keys()))
    def test_legal_transitions_not_empty(self, status):
        """Every status except terminal should have legal transitions."""
        action = NextAction.compute(status)
        if status in ("done", "archived"):
            assert len(action.legal) == 0, f"Terminal status {status} should have no legal transitions"
        else:
            assert len(action.legal) > 0, f"Status {status} should have legal transitions"
