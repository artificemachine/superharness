"""Tests for engine.report_verifier — RED tests for iter 6 of auto-mode-gap-plan.

Report verification gate: prevents auto_close_report_ready from blindly
closing reports that lack evidence of completion. Operator only sees reports
that fail verification.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def verify_report():
    from superharness.engine.report_verifier import verify_report
    return verify_report


def _good_report(**overrides) -> dict:
    base = {
        "task": "feat.foo",
        "phase": "report",
        "status": "report_ready",
        "from": "claude-code",
        "to": "owner",
        "outcome": (
            "Implemented compute() function that returns the expected value. "
            "All targeted tests pass. Existing helper unchanged. Verified end-to-end."
        ),
        "context": "Edge cases covered: empty input, large input, malformed input.",
        "tests_passed": True,
    }
    base.update(overrides)
    return base


def _good_task(**overrides) -> dict:
    base = {"id": "feat.foo", "owner": "claude-code", "status": "report_ready"}
    base.update(overrides)
    return base


def test_complete_report_passes_verification(verify_report, clean_harness: Path) -> None:
    r = verify_report(_good_report(), _good_task(), str(clean_harness))
    assert r.passed is True
    assert r.suggested_action == "close"


def test_report_missing_outcome_is_rejected(verify_report, clean_harness: Path) -> None:
    rep = _good_report()
    del rep["outcome"]
    r = verify_report(rep, _good_task(), str(clean_harness))
    assert r.passed is False
    assert any("outcome" in f.lower() for f in r.failures)


def test_report_with_short_outcome_is_rejected(verify_report, clean_harness: Path) -> None:
    rep = _good_report(outcome="done")
    r = verify_report(rep, _good_task(), str(clean_harness))
    assert r.passed is False
    assert any("outcome" in f.lower() and "short" in f.lower() for f in r.failures)


def test_report_missing_context_field_warns(verify_report, clean_harness: Path) -> None:
    rep = _good_report()
    del rep["context"]
    r = verify_report(rep, _good_task(), str(clean_harness))
    # Missing context is a soft warning, not a hard block
    assert any("context" in f.lower() for f in r.failures)


def test_report_with_tests_passed_false_is_rejected(verify_report, clean_harness: Path) -> None:
    rep = _good_report(tests_passed=False)
    r = verify_report(rep, _good_task(), str(clean_harness))
    assert r.passed is False
    assert r.suggested_action != "close"
    assert any("tests" in f.lower() for f in r.failures)


def test_report_referencing_nonexistent_pr_url_is_rejected(verify_report, clean_harness: Path) -> None:
    """If a report claims a PR URL, it should be a valid-looking URL."""
    rep = _good_report(pr_url="not a real url")
    r = verify_report(rep, _good_task(), str(clean_harness))
    assert r.passed is False
    assert any("pr_url" in f.lower() or "url" in f.lower() for f in r.failures)


def test_report_with_valid_pr_url_passes(verify_report, clean_harness: Path) -> None:
    rep = _good_report(pr_url="https://github.com/celstnblacc/superharness/pull/145")
    r = verify_report(rep, _good_task(), str(clean_harness))
    assert r.passed is True


def test_verification_returns_typed_result(verify_report, clean_harness: Path) -> None:
    from superharness.engine.report_verifier import ReportVerification

    r = verify_report(_good_report(), _good_task(), str(clean_harness))
    assert isinstance(r, ReportVerification)
    assert isinstance(r.passed, bool)
    assert isinstance(r.failures, list)
    assert r.suggested_action in ("close", "operator_review", "fail")


def test_verification_failure_routes_to_operator_review(verify_report, clean_harness: Path) -> None:
    rep = _good_report(outcome="done")  # too short
    r = verify_report(rep, _good_task(), str(clean_harness))
    assert r.passed is False
    assert r.suggested_action == "operator_review"
