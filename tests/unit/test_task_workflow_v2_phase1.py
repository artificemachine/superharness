"""RED phase tests for task-workflow-v2 Phase 1: new task fields.

Tests:
- ContractTask schema accepts effort, plan (alias tdd), out_of_scope,
  definition_of_done, context, timeout_minutes, progress_timeout_minutes
- Contract schema accepts default_definition_of_done
- task create CLI accepts the new flags
- Old contracts with tdd: key load into plan field (backward compat)
- No hardcoded development_method enum — any string accepted
- validate.py inherits default_definition_of_done
- validate.py warns on high/max effort without out_of_scope
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml


# ── Schema tests ──


pytestmark = pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")

def test_contract_task_effort_field():
    """ContractTask accepts effort field with valid values."""
    from superharness.engine.schemas import ContractTask

    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", effort="high",
    )
    assert task.effort == "high"


def test_contract_task_effort_default():
    """ContractTask defaults effort to 'medium'."""
    from superharness.engine.schemas import ContractTask

    task = ContractTask(
        id="t-1", title="test", owner="claude-code", status="todo",
    )
    assert task.effort == "medium"


def test_contract_task_plan_field_direct():
    """ContractTask accepts plan field directly."""
    from superharness.engine.schemas import ContractTask

    plan = {"red": "write test", "green": "implement", "refactor": "cleanup"}
    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", plan=plan,
    )
    assert task.plan == plan


def test_plan_field_reads_old_tdd_alias():
    """Old contracts with tdd: key load into plan field via alias."""
    from superharness.engine.schemas import ContractTask

    tdd_data = {"red": "write test", "green": "implement"}
    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", tdd=tdd_data,
    )
    assert task.plan == tdd_data


def test_contract_task_out_of_scope():
    """ContractTask accepts out_of_scope as list of strings."""
    from superharness.engine.schemas import ContractTask

    oos = ["no UI changes", "do not modify user model"]
    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", out_of_scope=oos,
    )
    assert task.out_of_scope == oos


def test_contract_task_definition_of_done():
    """ContractTask accepts definition_of_done as list of strings."""
    from superharness.engine.schemas import ContractTask

    dod = ["all tests pass", "no new warnings"]
    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", definition_of_done=dod,
    )
    assert task.definition_of_done == dod


def test_contract_task_context():
    """ContractTask accepts context as string."""
    from superharness.engine.schemas import ContractTask

    ctx = "Read src/api/ first. Auth middleware in middleware/"
    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", context=ctx,
    )
    assert task.context == ctx


def test_contract_task_timeout_minutes():
    """ContractTask accepts timeout_minutes."""
    from superharness.engine.schemas import ContractTask

    task = ContractTask(
        id="t-1", title="test", owner="claude-code",
        status="todo", timeout_minutes=25,
    )
    assert task.timeout_minutes == 25


def test_contract_task_progress_timeout_minutes():
    """ContractTask accepts progress_timeout_minutes with default 10."""
    from superharness.engine.schemas import ContractTask

    task = ContractTask(
        id="t-1", title="test", owner="claude-code", status="todo",
    )
    assert task.progress_timeout_minutes == 10


def test_contract_default_definition_of_done():
    """Contract accepts default_definition_of_done."""
    from superharness.engine.schemas import Contract

    dod = ["all tests pass", "no new warnings"]
    contract = Contract(
        id="test", created="2026-04-07", created_by="owner",
        status="active", default_definition_of_done=dod,
    )
    assert contract.default_definition_of_done == dod


# ── Development method — no hardcoded enum ──


def test_development_method_any_string(tmp_path):
    """task create accepts any string as development_method, not just tdd/bdd/sdd/none."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-any", title="test any method",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        development_method="atdd",
    )
    assert rc == 0


def test_task_create_development_method_atdd(tmp_path):
    """task create accepts 'atdd' as development_method."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-atdd", title="test atdd",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        development_method="atdd",
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-atdd")
    assert task["development_method"] == "atdd"


def test_task_create_development_method_custom(tmp_path):
    """task create accepts arbitrary development_method strings."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-custom", title="test custom",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        development_method="spike",
    )
    assert rc == 0


# ── task create with new fields ──


def test_task_create_with_effort(tmp_path):
    """task create writes effort field to contract."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-eff", title="test effort",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        effort="high",
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-eff")
    assert task["effort"] == "high"


def test_task_create_with_test_types(tmp_path):
    """task create writes test_types list to contract."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-tt", title="test types",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        test_types=["unit", "integration"],
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-tt")
    assert task["test_types"] == ["unit", "integration"]


def test_task_create_with_out_of_scope(tmp_path):
    """task create writes out_of_scope list to contract."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-oos", title="test oos",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        out_of_scope=["no UI changes"],
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-oos")
    assert task["out_of_scope"] == ["no UI changes"]


def test_task_create_with_definition_of_done(tmp_path):
    """task create writes definition_of_done list to contract."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-dod", title="test dod",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        definition_of_done=["all tests pass", "no warnings"],
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-dod")
    assert task["definition_of_done"] == ["all tests pass", "no warnings"]


def test_task_create_with_context(tmp_path):
    """task create writes context string to contract."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-ctx", title="test ctx",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        context="Read src/api/ first",
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-ctx")
    assert task["context"] == "Read src/api/ first"


def test_task_create_with_timeout_minutes(tmp_path):
    """task create writes timeout_minutes to contract."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    rc = create(
        contract_file, task_id="t-to", title="test timeout",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        timeout_minutes=20,
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-to")
    assert task["timeout_minutes"] == 20


def test_task_create_with_plan_bdd(tmp_path):
    """task create writes BDD plan phases."""
    from superharness.commands.task import create

    contract_file = _make_contract(tmp_path)
    plan = {"given": "user logged in", "when": "clicks buy", "then": "order created"}
    rc = create(
        contract_file, task_id="t-bdd", title="test bdd",
        owner="claude-code", status="todo",
        project_path=str(tmp_path),
        development_method="bdd",
        plan=plan,
    )
    assert rc == 0
    data = yaml.safe_load(open(contract_file))
    task = next(t for t in data["tasks"] if t["id"] == "t-bdd")
    # Written as "tdd" key for backward compat; Pydantic reads via alias into plan field
    assert task["tdd"] == plan


# ── Helpers ──


def _make_contract(tmp_path: Path) -> str:
    harness = tmp_path / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    contract_file = harness / "contract.yaml"
    contract_file.write_text(
        "id: test-contract\n"
        "created: 2026-04-07\n"
        "created_by: owner\n"
        "status: active\n"
        "tasks: []\n"
    )
    return str(contract_file)
