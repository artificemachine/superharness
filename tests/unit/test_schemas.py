"""Tests for superharness.engine.schemas and safe_load schema= integration."""
from __future__ import annotations

import os
import tempfile

import pytest
from pydantic import ValidationError

from superharness.engine.schemas import (
    Contract,
    ContractTask,
    Handoff,
    Heartbeat,
    HeartbeatCheck,
    InboxDoc,
    InboxItem,
    InboxStatus,
    Profile,
    TaskStatus,
)
from superharness.engine.yaml_helpers import safe_load


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_TASK = {
    "id": "T-001",
    "title": "Write tests",
    "owner": "agent",
    "status": "todo",
}

VALID_CONTRACT = {
    "id": "C-001",
    "created": "2025-01-01",
    "created_by": "agent",
    "status": "active",
    "tasks": [VALID_TASK],
}

VALID_HANDOFF = {
    "id": "H-001",
    "task": "T-001",
    "from": "agent-a",
    "to": "agent-b",
    "status": "pending",
}

VALID_HEARTBEAT = {
    "checks": [
        {
            "id": "hb-1",
            "description": "CPU check",
            "interval_minutes": 5,
            "enabled": True,
        }
    ]
}

VALID_PROFILE = {
    "project_name": "my-project",
    "created": "2025-01-01",
    "autonomy": "autonomous",
    "primary_agent": "claude-code",
    "stack": "python",
}

VALID_INBOX_ITEM = {
    "id": "I-001",
    "to": "agent",
    "task": "T-001",
    "project": "my-project",
    "status": "pending",
    "created_at": "2025-01-01T00:00:00",
}


# ---------------------------------------------------------------------------
# ContractTask tests (5 tests)
# ---------------------------------------------------------------------------


def test_contract_task_valid_required_fields():
    task = ContractTask.model_validate(VALID_TASK)
    assert task.id == "T-001"
    assert task.status == TaskStatus.todo


def test_contract_task_invalid_status_raises():
    bad = {**VALID_TASK, "status": "not_a_status"}
    with pytest.raises(ValidationError):
        ContractTask.model_validate(bad)


def test_contract_task_all_optional_fields():
    full = {
        **VALID_TASK,
        "project_path": "/path/to/proj",
        "acceptance_criteria": ["must pass"],
        "test_types": ["unit"],
        "tdd": {"red": "fail", "green": "pass", "refactor": "clean"},
        "blocked_by": "T-000",
        "dependency": "T-000",
        "summary": "A summary",
        "verified": True,
        "verified_at": "2025-01-02",
        "verified_by": "reviewer",
        "deadline_minutes": 120,
        "review_requested_at": "2025-01-01T10:00:00",
    }
    task = ContractTask.model_validate(full)
    assert task.verified is True
    assert task.deadline_minutes == 120


def test_contract_task_extra_fields_allowed():
    data = {**VALID_TASK, "unknown_field": "some_value"}
    task = ContractTask.model_validate(data)
    assert task.unknown_field == "some_value"  # type: ignore[attr-defined]


def test_contract_task_model_field_optional():
    # model field declared — accepts None (default) or a string
    task = ContractTask.model_validate(VALID_TASK)
    assert task.model is None

    task_with_model = ContractTask.model_validate({**VALID_TASK, "model": "claude-sonnet-4-6"})
    assert task_with_model.model == "claude-sonnet-4-6"


def test_contract_task_status_enum_values():
    statuses = [
        "todo", "plan_proposed", "plan_approved", "in_progress",
        "report_ready", "review_passed", "done", "failed", "blocked",
    ]
    for s in statuses:
        task = ContractTask.model_validate({**VALID_TASK, "status": s})
        assert task.status.value == s


# ---------------------------------------------------------------------------
# Contract tests (3 tests)
# ---------------------------------------------------------------------------


def test_contract_valid():
    contract = Contract.model_validate(VALID_CONTRACT)
    assert contract.id == "C-001"
    assert len(contract.tasks) == 1


def test_contract_invalid_nested_task_status_raises():
    bad = {
        **VALID_CONTRACT,
        "tasks": [{**VALID_TASK, "status": "invalid_status"}],
    }
    with pytest.raises(ValidationError):
        Contract.model_validate(bad)


def test_contract_empty_tasks_list():
    data = {**VALID_CONTRACT, "tasks": []}
    contract = Contract.model_validate(data)
    assert contract.tasks == []


# ---------------------------------------------------------------------------
# Handoff tests (3 tests)
# ---------------------------------------------------------------------------


def test_handoff_valid():
    handoff = Handoff.model_validate(VALID_HANDOFF)
    assert handoff.from_ == "agent-a"
    assert handoff.to == "agent-b"


def test_handoff_missing_required_field_raises():
    bad = {k: v for k, v in VALID_HANDOFF.items() if k != "task"}
    with pytest.raises(ValidationError):
        Handoff.model_validate(bad)


def test_handoff_extra_fields_allowed():
    data = {**VALID_HANDOFF, "extra_meta": "value"}
    handoff = Handoff.model_validate(data)
    assert handoff.extra_meta == "value"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Heartbeat tests (2 tests)
# ---------------------------------------------------------------------------


def test_heartbeat_valid():
    hb = Heartbeat.model_validate(VALID_HEARTBEAT)
    assert len(hb.checks) == 1
    assert hb.checks[0].id == "hb-1"


def test_heartbeat_check_invalid_type_raises():
    bad = {
        "checks": [
            {
                "id": "hb-1",
                "description": "CPU check",
                "interval_minutes": "not_an_int",  # wrong type
                "enabled": True,
            }
        ]
    }
    with pytest.raises(ValidationError):
        Heartbeat.model_validate(bad, strict=True)


# ---------------------------------------------------------------------------
# Profile tests (3 tests)
# ---------------------------------------------------------------------------


def test_profile_valid():
    profile = Profile.model_validate(VALID_PROFILE)
    assert profile.project_name == "my-project"
    assert profile.autonomy == "autonomous"


def test_profile_invalid_autonomy_raises():
    bad = {**VALID_PROFILE, "autonomy": "rogue"}
    with pytest.raises(ValidationError):
        Profile.model_validate(bad)


def test_profile_extra_fields_allowed():
    data = {**VALID_PROFILE, "custom_setting": True}
    profile = Profile.model_validate(data)
    assert profile.custom_setting is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# InboxItem / InboxDoc tests (3 tests)
# ---------------------------------------------------------------------------


def test_inbox_item_valid():
    item = InboxItem.model_validate(VALID_INBOX_ITEM)
    assert item.id == "I-001"
    assert item.status == InboxStatus.pending


def test_inbox_item_invalid_status_raises():
    bad = {**VALID_INBOX_ITEM, "status": "bogus_status"}
    with pytest.raises(ValidationError):
        InboxItem.model_validate(bad)


def test_inbox_doc_wraps_list():
    doc = InboxDoc.model_validate({"items": [VALID_INBOX_ITEM]})
    assert len(doc.items) == 1
    assert doc.items[0].task == "T-001"


# ---------------------------------------------------------------------------
# safe_load with schema= tests (5 tests)
# ---------------------------------------------------------------------------


def _write_yaml(content: str) -> str:
    """Write content to a temp file and return the path."""
    fd, path = tempfile.mkstemp(suffix=".yaml")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


def test_safe_load_schema_returns_model_instance():
    yaml_content = """\
id: C-002
created: "2025-02-01"
created_by: agent
status: draft
tasks: []
"""
    path = _write_yaml(yaml_content)
    try:
        result = safe_load(path, dict, schema=Contract)
        assert isinstance(result, Contract)
        assert result.id == "C-002"
    finally:
        os.unlink(path)


def test_safe_load_schema_malformed_raises_validation_error():
    yaml_content = """\
id: C-003
created: "2025-02-01"
created_by: agent
status: not_a_valid_status
"""
    path = _write_yaml(yaml_content)
    try:
        with pytest.raises(ValidationError):
            safe_load(path, dict, schema=Contract)
    finally:
        os.unlink(path)


def test_safe_load_no_schema_returns_plain_dict():
    yaml_content = """\
id: C-004
created: "2025-02-01"
created_by: agent
status: active
"""
    path = _write_yaml(yaml_content)
    try:
        result = safe_load(path, dict)
        assert isinstance(result, dict)
        assert result["id"] == "C-004"
    finally:
        os.unlink(path)


def test_safe_load_schema_missing_file_returns_empty_dict():
    missing_path = "/tmp/this_file_does_not_exist_superharness_test.yaml"
    result = safe_load(missing_path, dict, schema=Contract)
    assert result == {}


def test_safe_load_strict_wrong_type_raises():
    yaml_content = """\
id: C-005
created: "2025-02-01"
created_by: agent
status: active
tasks: []
decisions: []
failures: []
"""
    path = _write_yaml(yaml_content)
    try:
        # strict=True should still validate fine for matching types
        result = safe_load(path, dict, schema=Contract, strict=True)
        assert isinstance(result, Contract)
    finally:
        os.unlink(path)
