"""Tests for engine/model_budget.py — budget guard enforcement (TDD: written before implementation)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def project(tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    return tmp_path


def _write_benchmark(project: Path, records: list[dict]) -> None:
    bm = project / ".superharness" / "benchmark.jsonl"
    bm.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _write_profile(project: Path, doc: dict) -> None:
    import yaml
    (project / ".superharness" / "profile.yaml").write_text(yaml.dump(doc))


# ---------------------------------------------------------------------------
# Budget check
# ---------------------------------------------------------------------------

def test_budget_warn_at_threshold(project, capsys):
    """80%+ of daily limit → CheckResult.status == 'warn'."""
    from superharness.engine.model_budget import check_budget, BudgetStatus
    import datetime

    today = datetime.date.today().isoformat()
    _write_benchmark(project, [
        {"task_id": "t1", "cost_usd": 4.10, "timestamp": f"{today}T10:00:00+00:00"},
    ])
    _write_profile(project, {"budget": {"daily_limit": 5.00, "strict": False}})

    result = check_budget(str(project))
    assert result.status == BudgetStatus.WARN, f"Expected WARN, got {result.status}"
    assert result.used_today >= 4.10
    assert result.daily_limit == 5.00


def test_budget_block_when_exceeded_strict(project):
    """Strict mode + over daily limit → BudgetStatus.BLOCK."""
    from superharness.engine.model_budget import check_budget, BudgetStatus
    import datetime

    today = datetime.date.today().isoformat()
    _write_benchmark(project, [
        {"task_id": "t1", "cost_usd": 5.50, "timestamp": f"{today}T10:00:00+00:00"},
    ])
    _write_profile(project, {"budget": {"daily_limit": 5.00, "strict": True}})

    result = check_budget(str(project))
    assert result.status == BudgetStatus.BLOCK


def test_budget_warn_only_when_not_strict(project):
    """Non-strict mode + over daily limit → BudgetStatus.WARN (not BLOCK)."""
    from superharness.engine.model_budget import check_budget, BudgetStatus
    import datetime

    today = datetime.date.today().isoformat()
    _write_benchmark(project, [
        {"task_id": "t1", "cost_usd": 6.00, "timestamp": f"{today}T10:00:00+00:00"},
    ])
    _write_profile(project, {"budget": {"daily_limit": 5.00, "strict": False}})

    result = check_budget(str(project))
    assert result.status == BudgetStatus.WARN


def test_budget_ok_under_threshold(project):
    """Under 80% of daily limit → BudgetStatus.OK."""
    from superharness.engine.model_budget import check_budget, BudgetStatus
    import datetime

    today = datetime.date.today().isoformat()
    _write_benchmark(project, [
        {"task_id": "t1", "cost_usd": 1.00, "timestamp": f"{today}T10:00:00+00:00"},
    ])
    _write_profile(project, {"budget": {"daily_limit": 5.00, "strict": False}})

    result = check_budget(str(project))
    assert result.status == BudgetStatus.OK
