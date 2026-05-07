"""Tests for MCP ApprovalGate — Iteration 3."""
from __future__ import annotations

import pytest
from pathlib import Path

from superharness.mcp.approval import ApprovalGate, ApprovalPending, ApprovalRejected


def test_low_risk_tool_auto_approved(tmp_path):
    gate = ApprovalGate()
    result = gate.check("get_contract", conn_id="c1", project_path=str(tmp_path))
    assert result is True  # auto-approved


def test_high_risk_tool_requires_approval(tmp_path):
    gate = ApprovalGate()
    with pytest.raises(ApprovalPending):
        gate.check("checkpoint_create", conn_id="c1", project_path=str(tmp_path))


def test_medium_risk_tool_raises_pending(tmp_path):
    gate = ApprovalGate()
    with pytest.raises(ApprovalPending):
        gate.check("enqueue", conn_id="c1", project_path=str(tmp_path))


def test_approve_clears_pending(tmp_path):
    gate = ApprovalGate()
    approval_id = None
    try:
        gate.check("enqueue", conn_id="c1", project_path=str(tmp_path))
    except ApprovalPending as e:
        approval_id = e.approval_id
    assert approval_id is not None
    gate.approve(approval_id)
    # Now the same op should be auto-approved
    result = gate.check("enqueue", conn_id="c1", project_path=str(tmp_path))
    assert result is True


def test_rejection_blocks_retries(tmp_path):
    gate = ApprovalGate()
    approval_id = None
    try:
        gate.check("enqueue", conn_id="c2", project_path=str(tmp_path))
    except ApprovalPending as e:
        approval_id = e.approval_id
    gate.reject(approval_id)
    with pytest.raises(ApprovalRejected):
        gate.check("enqueue", conn_id="c2", project_path=str(tmp_path))


def test_classify_risk_read_tools_are_low():
    from superharness.mcp.approval import classify_risk
    assert classify_risk("get_contract") == "low"
    assert classify_risk("get_task") == "low"
    assert classify_risk("get_ledger") == "low"
    assert classify_risk("get_inbox") == "low"


def test_classify_risk_write_tools_are_medium():
    from superharness.mcp.approval import classify_risk
    assert classify_risk("create_task") == "medium"
    assert classify_risk("update_status") == "medium"
    assert classify_risk("enqueue") == "medium"


def test_classify_risk_destructive_tools_are_high():
    from superharness.mcp.approval import classify_risk
    assert classify_risk("checkpoint_create") == "high"
    assert classify_risk("write_handoff") == "high"


def test_unknown_tool_defaults_to_medium():
    from superharness.mcp.approval import classify_risk
    assert classify_risk("some_future_tool") == "medium"
