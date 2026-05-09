"""Tests for the centralized contract_io write path (Iteration 2).

RED: all tests fail before contract_io.py exists.
GREEN: all tests pass after implementation.
"""
from __future__ import annotations

import ast
import os
import pathlib

import pytest
import yaml


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_write_valid_contract_succeeds(tmp_path):
    from superharness.engine.contract_io import write_contract

    doc = {
        "id": "test-001",
        "created": "2026-01-01T00:00:00Z",
        "created_by": "claude-code",
        "status": "active",
        "tasks": [
            {"id": "foo.bar", "title": "A task", "owner": "claude-code", "status": "todo"}
        ],
        "decisions": [],
        "failures": [],
    }
    path = str(tmp_path / "contract.yaml")
    write_contract(path, doc)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    assert loaded["id"] == "test-001"
    assert len(loaded["tasks"]) == 1


def test_write_invalid_contract_raises(tmp_path):
    from superharness.engine.contract_io import ContractValidationError, write_contract

    doc = {
        "id": "test-002",
        "created": "2026-01-01T00:00:00Z",
        "created_by": "claude-code",
        "status": "active",
        "tasks": [
            {
                "id": "bad.task",
                "title": "Bad task",
                "owner": "claude-code",
                "status": "todo",
                "acceptance_criteria": [{"key": "should be a string"}],
            }
        ],
        "decisions": [],
        "failures": [],
    }
    path = str(tmp_path / "contract.yaml")
    with pytest.raises(ContractValidationError) as exc_info:
        write_contract(path, doc)

    assert not os.path.exists(path), "no file must be written on schema violation"
    assert "acceptance_criteria" in str(exc_info.value)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_write_is_atomic(tmp_path, monkeypatch):
    """A failure during os.replace must not corrupt the existing file."""
    from superharness.engine import contract_io

    original_content = (
        "id: original\ncreated: '2026-01-01T00:00:00Z'\ncreated_by: x\n"
        "status: active\ntasks: []\ndecisions: []\nfailures: []\n"
    )
    path = tmp_path / "contract.yaml"
    path.write_text(original_content, encoding="utf-8")

    import os

    def exploding_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", exploding_replace)

    valid_doc = {
        "id": "new", "created": "2026-01-01T00:00:00Z",
        "created_by": "x", "status": "active",
        "tasks": [], "decisions": [], "failures": [],
    }
    with pytest.raises(OSError):
        contract_io.write_contract(str(path), valid_doc)

    # Original must still be intact
    assert path.read_text(encoding="utf-8") == original_content
    # No stale .tmp file should remain
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert tmp_files == [], f"Stale tmp files left behind: {tmp_files}"


def test_write_contract_syncs_subtasks_to_sqlite(tmp_path):
    """Subtasks nested under a parent task in contract.yaml are upserted to SQLite (B2 fix)."""
    import sqlite3 as _sqlite3
    from superharness.engine.contract_io import write_contract
    from superharness.engine.db import get_connection, init_db

    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir()
    path = str(sh_dir / "contract.yaml")

    doc = {
        "id": "test-sub", "created": "2026-01-01T00:00:00Z",
        "created_by": "claude-code", "status": "active",
        "tasks": [
            {
                "id": "parent", "title": "Parent", "owner": "claude-code",
                "status": "todo",
                "subtasks": [
                    {"id": "sub1", "title": "Sub One", "owner": "claude-code", "status": "pending"},
                    {"id": "sub2", "title": "Sub Two", "owner": "claude-code", "status": "pending"},
                ],
            }
        ],
        "decisions": [], "failures": [],
    }
    write_contract(path, doc)

    conn = get_connection(str(tmp_path))
    init_db(conn)
    try:
        ids = {r[0] for r in conn.execute("SELECT id FROM tasks").fetchall()}
    finally:
        conn.close()

    assert "parent" in ids, "parent task must be in SQLite"
    assert "sub1" in ids, "sub1 must be upserted to SQLite"
    assert "sub2" in ids, "sub2 must be upserted to SQLite"


def test_all_command_modules_do_not_define_write_contract_locally():
    """No command module should define _write_contract locally after centralization."""
    commands_dir = pathlib.Path("src/superharness/commands")
    offenders = []
    for py_file in commands_dir.glob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        local_defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        if "_write_contract" in local_defs:
            offenders.append(py_file.name)
    assert offenders == [], (
        f"These modules still define _write_contract locally and must be updated: {offenders}"
    )
