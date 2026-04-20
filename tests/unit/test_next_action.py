"""Unit tests for engine/next_action.py — pure function, no I/O."""
from __future__ import annotations

import pytest

from superharness.engine.next_action import ALL_STATUSES, NextAction, next_action


class TestNextActionBasicMapping:
    def test_todo_recommends_plan_proposed(self):
        r = next_action("todo")
        assert r.recommended == "plan_proposed"
        assert "plan_proposed" in r.legal

    def test_plan_proposed_recommends_plan_approved(self):
        r = next_action("plan_proposed")
        assert r.recommended == "plan_approved"
        assert "plan_approved" in r.legal

    def test_plan_approved_recommends_in_progress(self):
        r = next_action("plan_approved")
        assert r.recommended == "in_progress"

    def test_in_progress_recommended_is_none(self):
        r = next_action("in_progress")
        assert r.recommended is None
        assert r.legal  # still has valid transitions

    def test_review_failed_recommends_plan_proposed(self):
        r = next_action("review_failed")
        assert r.recommended == "plan_proposed"

    def test_failed_recommends_plan_proposed(self):
        r = next_action("failed")
        assert r.recommended == "plan_proposed"

    def test_done_is_terminal(self):
        r = next_action("done")
        assert r.recommended is None
        assert r.legal == []

    def test_archived_is_terminal(self):
        r = next_action("archived")
        assert r.recommended is None
        assert r.legal == []

    def test_stopped_recommends_in_progress(self):
        r = next_action("stopped")
        assert r.recommended == "in_progress"

    def test_pending_user_approval_recommends_in_progress(self):
        r = next_action("pending_user_approval")
        assert r.recommended == "in_progress"

    def test_report_ready_recommends_review_passed(self):
        r = next_action("report_ready")
        assert r.recommended == "review_passed"

    def test_review_passed_recommends_done(self):
        r = next_action("review_passed")
        assert r.recommended == "done"


class TestNextActionInvariants:
    def test_recommended_is_member_of_legal_or_none(self):
        for status in ALL_STATUSES:
            r = next_action(status)
            if r.recommended is not None:
                assert r.recommended in r.legal, (
                    f"status={status}: recommended={r.recommended!r} not in legal={r.legal}"
                )

    def test_legal_is_subset_of_all_statuses(self):
        known = set(ALL_STATUSES)
        for status in ALL_STATUSES:
            r = next_action(status)
            for s in r.legal:
                assert s in known, f"status={status}: legal contains unknown status {s!r}"

    def test_reason_is_nonempty_string(self):
        for status in ALL_STATUSES:
            r = next_action(status)
            assert isinstance(r.reason, str) and r.reason.strip(), (
                f"status={status}: reason is empty"
            )

    def test_all_statuses_have_mapping(self):
        for status in ALL_STATUSES:
            r = next_action(status)
            assert isinstance(r, NextAction)

    def test_as_dict_shape(self):
        r = next_action("todo")
        d = r.as_dict()
        assert set(d.keys()) == {"recommended", "legal", "reason"}
        assert isinstance(d["legal"], list)
        assert isinstance(d["reason"], str)


class TestNextActionUnknownStatus:
    def test_unknown_status_returns_safe_defaults(self):
        r = next_action("xyzzy_unknown")
        assert r.recommended is None
        assert r.legal == []
        assert "unknown" in r.reason.lower() or "xyzzy" in r.reason


class TestNextActionMissingStatuses:
    """Every status the state machine knows about must be in ALL_STATUSES."""

    def test_blocked_is_in_all_statuses(self):
        assert "blocked" in ALL_STATUSES

    def test_pr_open_is_in_all_statuses(self):
        assert "pr_open" in ALL_STATUSES

    def test_waiting_input_is_in_all_statuses(self):
        assert "waiting_input" in ALL_STATUSES

    def test_paused_is_in_all_statuses(self):
        assert "paused" in ALL_STATUSES

    def test_archived_is_in_all_statuses(self):
        assert "archived" in ALL_STATUSES
