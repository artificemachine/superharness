"""Tests for MCP ledger + handoff tools — Iteration 7."""
from __future__ import annotations

import pytest
from pathlib import Path


def _sh(tmp_path: Path) -> Path:
    sh = tmp_path / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    return sh


# ── Ledger ────────────────────────────────────────────────────────────────────

def test_get_ledger_returns_last_n_lines(tmp_path):
    from superharness.mcp.tools.ledger import get_ledger, append_ledger
    _sh(tmp_path)
    for i in range(20):
        append_ledger(str(tmp_path), f"entry {i}")
    lines = get_ledger(str(tmp_path), n=5)
    assert len(lines) == 5
    assert "entry 19" in lines[-1]


def test_append_ledger_creates_if_missing(tmp_path):
    from superharness.mcp.tools.ledger import append_ledger, get_ledger
    _sh(tmp_path)
    append_ledger(str(tmp_path), "first entry")
    lines = get_ledger(str(tmp_path), n=10)
    assert len(lines) == 1


def test_append_ledger_is_append_only(tmp_path):
    from superharness.mcp.tools.ledger import append_ledger, get_ledger
    _sh(tmp_path)
    append_ledger(str(tmp_path), "line 1")
    append_ledger(str(tmp_path), "line 2")
    lines = get_ledger(str(tmp_path), n=10)
    assert len(lines) == 2
    assert "line 1" in lines[0]
    assert "line 2" in lines[1]


# ── Handoffs ──────────────────────────────────────────────────────────────────

def test_get_handoffs_lists_yaml_files(tmp_path):
    from superharness.mcp.tools.handoffs import get_handoffs, write_handoff
    _sh(tmp_path)
    write_handoff(str(tmp_path), task_id="t1", phase="plan", content={"summary": "x"})
    write_handoff(str(tmp_path), task_id="t2", phase="report", content={"summary": "y"})
    items = get_handoffs(str(tmp_path))
    assert len(items) == 2


def test_get_handoffs_filters_by_phase(tmp_path):
    from superharness.mcp.tools.handoffs import get_handoffs, write_handoff
    _sh(tmp_path)
    write_handoff(str(tmp_path), task_id="t1", phase="plan", content={"summary": "plan"})
    write_handoff(str(tmp_path), task_id="t2", phase="report", content={"summary": "report"})
    items = get_handoffs(str(tmp_path), phase="report")
    assert all(h.get("phase") == "report" for h in items)
    assert len(items) == 1


def test_write_handoff_creates_file(tmp_path):
    from superharness.mcp.tools.handoffs import write_handoff, get_handoffs
    _sh(tmp_path)
    write_handoff(str(tmp_path), task_id="new-task", phase="plan", content={"note": "hello"})
    items = get_handoffs(str(tmp_path))
    assert len(items) == 1
    assert items[0].get("task_id") == "new-task"
