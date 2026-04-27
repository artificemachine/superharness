"""Tests for engine.plan_validator — RED tests for iter 5 of auto-mode-gap-plan.

Plan quality gate: prevents auto_approve_plans from blindly approving
incomplete plans. Operator only sees plans that fail quality checks.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def validate_plan():
    from superharness.engine.plan_validator import validate_plan
    return validate_plan


def _good_plan(**overrides) -> dict:
    base = {
        "task": "feat.foo",
        "phase": "plan",
        "status": "plan_proposed",
        "from": "claude-code",
        "to": "owner",
        "plan": (
            "Implement feat.foo by adding compute() that returns the expected value. "
            "Existing helper is not modified — wraps it instead."
        ),
        "tdd": {
            "red": "Write test_compute_returns_expected_value that fails because compute is missing.",
            "green": "Add compute() function that returns the expected value from input.",
            "refactor": "Extract validation helper. Verify existing helper not modified.",
        },
        "risks": "Edge case: empty input. Mitigated by guard at line 12.",
    }
    base.update(overrides)
    return base


def _good_task(**overrides) -> dict:
    base = {
        "id": "feat.foo",
        "owner": "claude-code",
        "status": "plan_proposed",
        "acceptance_criteria": [
            "compute returns expected value",
            "existing helper is not modified",
        ],
    }
    base.update(overrides)
    return base


def test_complete_plan_passes_validation(validate_plan) -> None:
    r = validate_plan(_good_plan(), _good_task())
    assert r.passed is True
    assert r.failures == []


def test_plan_missing_tdd_block_is_rejected(validate_plan) -> None:
    plan = _good_plan()
    del plan["tdd"]
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("tdd" in f.lower() for f in r.failures)


def test_plan_missing_tdd_red_section_is_rejected(validate_plan) -> None:
    plan = _good_plan()
    del plan["tdd"]["red"]
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("red" in f.lower() for f in r.failures)


def test_plan_missing_tdd_green_section_is_rejected(validate_plan) -> None:
    plan = _good_plan()
    del plan["tdd"]["green"]
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("green" in f.lower() for f in r.failures)


def test_plan_missing_tdd_refactor_section_is_rejected(validate_plan) -> None:
    plan = _good_plan()
    del plan["tdd"]["refactor"]
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("refactor" in f.lower() for f in r.failures)


def test_plan_with_empty_plan_field_is_rejected(validate_plan) -> None:
    plan = _good_plan(plan="")
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("plan" in f.lower() and ("empty" in f.lower() or "missing" in f.lower())
               for f in r.failures)


def test_plan_with_todo_marker_is_rejected(validate_plan) -> None:
    plan = _good_plan(plan="Implement TODO: figure out how")
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("todo" in f.lower() or "placeholder" in f.lower() for f in r.failures)


def test_plan_with_no_risks_section_is_rejected(validate_plan) -> None:
    plan = _good_plan()
    del plan["risks"]
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    assert any("risk" in f.lower() for f in r.failures)


def test_validation_failure_includes_actionable_reason(validate_plan) -> None:
    """Failure messages should be specific enough to act on."""
    plan = _good_plan()
    del plan["tdd"]
    r = validate_plan(plan, _good_task())
    assert r.passed is False
    # All failures should be non-empty strings
    assert all(isinstance(f, str) and len(f) > 0 for f in r.failures)


def test_validation_returns_typed_result(validate_plan) -> None:
    from superharness.engine.plan_validator import PlanValidation

    r = validate_plan(_good_plan(), _good_task())
    assert isinstance(r, PlanValidation)
    assert isinstance(r.passed, bool)
    assert isinstance(r.failures, list)
