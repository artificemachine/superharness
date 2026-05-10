"""Unit tests for Iter 4: ReviewFanout — parallel code-review subagents."""
from __future__ import annotations

import pytest

from superharness.engine.review_fanout import (
    ReviewFanout,
    ReviewResult,
    merge_review_results,
)


class TestMergeReviewResults:
    def test_all_pass_produces_passed_verdict(self):
        results = [
            ReviewResult(task_id="t1", passed=True),
            ReviewResult(task_id="t2", passed=True),
        ]
        verdict = merge_review_results(results)
        assert verdict.passed is True
        assert verdict.findings == []
        assert verdict.review_count == 2

    def test_one_fail_produces_failed_verdict(self):
        results = [
            ReviewResult(task_id="t1", passed=True),
            ReviewResult(task_id="t2", passed=False, findings=["missing test"]),
        ]
        verdict = merge_review_results(results)
        assert verdict.passed is False
        assert "missing test" in verdict.findings

    def test_all_fail_aggregates_all_findings(self):
        results = [
            ReviewResult(task_id="t1", passed=False, findings=["bug A"]),
            ReviewResult(task_id="t2", passed=False, findings=["bug B", "bug C"]),
        ]
        verdict = merge_review_results(results)
        assert verdict.passed is False
        assert set(verdict.findings) == {"bug A", "bug B", "bug C"}

    def test_empty_results_passes(self):
        verdict = merge_review_results([])
        assert verdict.passed is True
        assert verdict.findings == []
        assert verdict.review_count == 0


class TestReviewFanoutStructure:
    def test_fanout_created_with_task_ids(self, tmp_path):
        fanout = ReviewFanout(str(tmp_path), ["t1", "t2", "t3"])
        assert fanout.task_ids == ["t1", "t2", "t3"]

    def test_fanout_run_returns_verdict_with_correct_count(self, tmp_path, monkeypatch):
        # Stub _review_one to avoid subprocess dispatch
        def _stub_review(task_id: str) -> ReviewResult:
            return ReviewResult(task_id=task_id, passed=True)

        fanout = ReviewFanout(str(tmp_path), ["t1", "t2"])
        monkeypatch.setattr(fanout, "_review_one", _stub_review)
        verdict = fanout.run(max_workers=2)
        assert verdict.review_count == 2
        assert verdict.passed is True

    def test_fanout_run_propagates_failure(self, tmp_path, monkeypatch):
        def _stub_review(task_id: str) -> ReviewResult:
            if task_id == "t2":
                return ReviewResult(task_id=task_id, passed=False, findings=["error"])
            return ReviewResult(task_id=task_id, passed=True)

        fanout = ReviewFanout(str(tmp_path), ["t1", "t2", "t3"])
        monkeypatch.setattr(fanout, "_review_one", _stub_review)
        verdict = fanout.run(max_workers=3)
        assert verdict.passed is False
        assert "error" in verdict.findings
