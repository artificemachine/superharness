"""TDD: structured compaction block in handoff_generator.

Each handoff must include a `compaction` section with 5 keys that give
the next agent session enough context to continue without re-reading the
full contract or prior handoffs.
"""
from __future__ import annotations

import pytest


def _make_task(**kwargs):
    base = {
        "id": "test.task",
        "title": "Build the thing",
        "status": "in_progress",
        "acceptance_criteria": ["Thing is built", "Tests pass"],
        "context": "Replaces legacy approach",
        "out_of_scope": "UI layer",
        "tdd": '{"red": "write tests", "green": "implement", "refactor": "clean up"}',
    }
    base.update(kwargs)
    return base


class TestCompactionBlock:
    def _gen(self, task, tmp_path):
        from superharness.engine.handoff_generator import generate_handoff
        from unittest.mock import patch
        with patch("superharness.engine.handoff_generator._load_task", return_value=task):
            return generate_handoff(str(tmp_path), task["id"])

    def test_compaction_key_present(self, tmp_path):
        result = self._gen(_make_task(), tmp_path)
        assert "compaction" in result

    def test_compaction_has_all_five_keys(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        for key in ("goal", "constraints", "progress", "decisions", "next_steps"):
            assert key in c, f"missing key: {key}"

    def test_goal_includes_title(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        assert "Build the thing" in c["goal"]

    def test_goal_includes_acceptance_criteria(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        assert "Thing is built" in str(c["goal"])

    def test_constraints_includes_out_of_scope(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        assert "UI layer" in str(c["constraints"])

    def test_progress_reflects_status(self, tmp_path):
        c = self._gen(_make_task(status="report_ready"), tmp_path)["compaction"]
        assert "report_ready" in c["progress"].lower() or "complete" in c["progress"].lower()

    def test_progress_includes_tdd_phase(self, tmp_path):
        c = self._gen(_make_task(status="in_progress"), tmp_path)["compaction"]
        assert any(word in c["progress"].lower() for word in ("green", "red", "refactor", "tdd", "implement"))

    def test_decisions_is_list(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        assert isinstance(c["decisions"], list)

    def test_next_steps_is_list(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        assert isinstance(c["next_steps"], list)

    def test_next_steps_nonempty(self, tmp_path):
        c = self._gen(_make_task(), tmp_path)["compaction"]
        assert len(c["next_steps"]) > 0

    def test_next_steps_for_plan_approved(self, tmp_path):
        c = self._gen(_make_task(status="plan_approved"), tmp_path)["compaction"]
        combined = " ".join(c["next_steps"]).lower()
        assert any(w in combined for w in ("implement", "test", "run", "verify", "report"))

    def test_no_tdd_still_produces_compaction(self, tmp_path):
        c = self._gen(_make_task(tdd=None), tmp_path)["compaction"]
        assert "progress" in c

    def test_backward_compat_summary_still_present(self, tmp_path):
        result = self._gen(_make_task(), tmp_path)
        assert "summary" in result
