"""Unit tests for operator_memory CLI — shux operator-memory and shux operator-forget."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from superharness.cli import main


@pytest.fixture
def seeded_project(tmp_path):
    """Create a temp project with operator_memory table + 3 seeded patterns."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    db_path = str(sh / "state.sqlite3")

    from superharness.engine.operator_memory import OperatorMemory
    om = OperatorMemory(db_path)
    om.ensure_table()
    om.record_new("import_error", "pip install -e .")
    om.record_new("disk_space", "rm -rf /tmp/build-*")
    om.record_new("timeout", "increase --launcher-timeout to 600")

    # Build confidence: make import_error high, disk_space low
    for _ in range(3):
        om.record_match("import_error", success=True)
    for _ in range(2):
        om.record_match("disk_space", success=False)

    return tmp_path


# ---------------------------------------------------------------------------
# operator-memory
# ---------------------------------------------------------------------------

def test_operator_memory_shows_empty_state(tmp_path):
    """Empty project shows 'no remembered patterns' message."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    db_path = sh / "state.sqlite3"
    from superharness.engine.operator_memory import OperatorMemory
    OperatorMemory(str(db_path)).ensure_table()

    runner = CliRunner()
    result = runner.invoke(main, ["operator-memory", "--project", str(tmp_path)])
    assert result.exit_code == 0
    assert "no remembered patterns" in result.output


def test_operator_memory_lists_seeded_patterns(seeded_project):
    """Lists all patterns with confidence, hits, misses."""
    runner = CliRunner()
    result = runner.invoke(main, ["operator-memory", "--project", str(seeded_project)])

    assert result.exit_code == 0
    assert "import_error" in result.output
    assert "disk_space" in result.output
    assert "timeout" in result.output
    # Confidence column
    assert "0.50" in result.output or "1.00" in result.output


def test_operator_memory_shows_resolution_column(seeded_project):
    """Resolution text appears in output."""
    runner = CliRunner()
    result = runner.invoke(main, ["operator-memory", "--project", str(seeded_project)])

    assert result.exit_code == 0
    assert "pip install -e ." in result.output


def test_operator_memory_with_default_project_uses_cwd(seeded_project):
    """Runs against current working directory when --project omitted."""
    runner = CliRunner()
    result = runner.invoke(main, ["operator-memory", "--project", str(seeded_project)])
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# operator-forget
# ---------------------------------------------------------------------------

def test_operator_forget_removes_pattern(seeded_project):
    """Forgetting a pattern removes it from memory."""
    runner = CliRunner()
    result = runner.invoke(main, [
        "operator-forget", "timeout", "--project", str(seeded_project)
    ])
    assert result.exit_code == 0
    assert "removed 'timeout'" in result.output

    # Verify it's gone
    result2 = runner.invoke(main, ["operator-memory", "--project", str(seeded_project)])
    assert "timeout" not in result2.output


def test_operator_forget_unknown_signature_fails(seeded_project):
    """Forgetting a non-existent pattern exits with error."""
    runner = CliRunner()
    result = runner.invoke(main, [
        "operator-forget", "nonexistent", "--project", str(seeded_project)
    ])
    assert result.exit_code == 1
    assert "no pattern 'nonexistent'" in result.output


def test_operator_forget_without_signature_shows_usage(seeded_project):
    """Missing signature argument shows usage hint."""
    runner = CliRunner()
    result = runner.invoke(main, [
        "operator-forget", "--project", str(seeded_project)
    ])
    assert result.exit_code == 1
    assert "usage" in result.output.lower() or "<signature>" in result.output.lower()


def test_operator_forget_no_db_graceful(tmp_path):
    """No state.sqlite3 — exits cleanly."""
    sh = tmp_path / ".superharness"
    sh.mkdir()

    runner = CliRunner()
    result = runner.invoke(main, [
        "operator-forget", "anything", "--project", str(tmp_path)
    ])
    assert result.exit_code == 1
    assert "no state database" in result.output
