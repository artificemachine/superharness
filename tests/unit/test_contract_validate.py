"""Tests for shux contract --validate (Iteration 1).

RED: all tests fail before contract_validate.py exists.
GREEN: all tests pass after implementation.
"""
from __future__ import annotations

import os
import sys
import textwrap

import pytest
import yaml


def _run_validate(tmp_path, contract_content: str | None) -> tuple[int, str, str]:
    """Write contract to tmp_path and call validate_contract(); capture output."""
    from io import StringIO

    if contract_content is not None:
        contract_file = tmp_path / ".superharness" / "contract.yaml"
        contract_file.parent.mkdir(parents=True, exist_ok=True)
        contract_file.write_text(contract_content, encoding="utf-8")

    from superharness.commands.contract_validate import validate_contract

    stdout_buf, stderr_buf = StringIO(), StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = stdout_buf, stderr_buf
    try:
        rc = validate_contract(str(tmp_path))
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    return rc, stdout_buf.getvalue(), stderr_buf.getvalue()


_VALID_CONTRACT = textwrap.dedent("""\
    id: test-contract-001
    created: "2026-01-01T00:00:00Z"
    created_by: claude-code
    status: active
    tasks:
      - id: foo.bar
        title: A task
        owner: claude-code
        status: todo
    decisions: []
    failures: []
""")

_INVALID_YAML = "tasks: [\nnot: valid yaml {{{"

_AC_DICT_CONTRACT = textwrap.dedent("""\
    tasks:
      - id: foo.bar
        title: A task
        owner: claude-code
        status: todo
        acceptance_criteria:
          - {key: value that should be a string}
    decisions: []
    failures: []
""")

_TWO_BAD_TASKS = textwrap.dedent("""\
    tasks:
      - id: foo.bar
        title: A task
        owner: claude-code
        status: todo
        acceptance_criteria:
          - {key: value}
      - id: baz.qux
        title: Another task
        owner: claude-code
        status: todo
        acceptance_criteria:
          - {key: value2}
    decisions: []
    failures: []
""")


def test_validate_clean_contract_exits_zero(tmp_path):
    rc, out, err = _run_validate(tmp_path, _VALID_CONTRACT)
    assert rc == 0
    assert "OK" in out or "ok" in out.lower()


def test_validate_invalid_yaml_exits_nonzero(tmp_path):
    rc, out, err = _run_validate(tmp_path, _INVALID_YAML)
    assert rc != 0
    assert "YAML" in err or "yaml" in err.lower() or "parse" in err.lower()


def test_validate_schema_violation_exits_nonzero(tmp_path):
    rc, out, err = _run_validate(tmp_path, _AC_DICT_CONTRACT)
    assert rc != 0
    assert "acceptance_criteria" in err


def test_validate_missing_contract_exits_nonzero(tmp_path):
    rc, out, err = _run_validate(tmp_path, None)
    assert rc != 0
    combined = out + err
    assert "not found" in combined.lower() or "no such" in combined.lower()


def test_validate_reports_all_errors_not_just_first(tmp_path):
    rc, out, err = _run_validate(tmp_path, _TWO_BAD_TASKS)
    assert rc != 0
    # Both field paths must appear — not just the first error
    combined = out + err
    count = combined.count("acceptance_criteria")
    assert count >= 2, f"Expected at least 2 acceptance_criteria mentions, got {count}"
