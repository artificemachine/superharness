"""Unit tests for operator memory hooks — _seed_operator_memory and _check_operator_memory."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from superharness.engine.failure_patterns import (
    FailurePattern,
    _seed_operator_memory,
)
from superharness.engine.operator_memory import OperatorMemory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_with_table(tmp_path):
    """Create a temp project with operator_memory table."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    db_path = str(sh / "state.sqlite3")
    om = OperatorMemory(db_path)
    om.ensure_table()
    return tmp_path


@pytest.fixture
def sample_patterns():
    """Two failure patterns with different resolutions."""
    return [
        FailurePattern(
            id="import_error",
            description="Import error",
            match_patterns=[r"ModuleNotFoundError"],
            hint="Check deps",
            remediation="pip install -e .",
            severity="major",
        ),
        FailurePattern(
            id="timeout",
            description="Timeout",
            match_patterns=[r"TimeoutError"],
            hint="Increase timeout",
            remediation="",
            severity="major",
        ),
    ]


# ---------------------------------------------------------------------------
# _seed_operator_memory
# ---------------------------------------------------------------------------

def test_seed_creates_new_patterns(db_with_table, sample_patterns):
    """Seeding unknown patterns creates entries in operator_memory."""
    _seed_operator_memory(str(db_with_table), sample_patterns)

    db_path = str(db_with_table / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)

    imp = om.find_pattern("import_error")
    assert imp is not None
    assert imp["resolution"] == "pip install -e ."
    assert imp["confidence"] == 0.5

    to = om.find_pattern("timeout")
    assert to is not None
    assert to["resolution"] == "Increase timeout"  # falls back to hint
    assert to["confidence"] == 0.5


def test_seed_skips_existing_patterns(db_with_table, sample_patterns):
    """Seeding an already-known pattern does not overwrite it."""
    db_path = str(db_with_table / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)

    # Pre-seed with a different resolution
    om.record_new("import_error", "original fix")

    # Now seed — should skip, not overwrite
    _seed_operator_memory(str(db_with_table), sample_patterns[:1])

    result = om.find_pattern("import_error")
    assert result["resolution"] == "original fix"  # unchanged


def test_seed_handles_missing_sqlite_gracefully(tmp_path):
    """Seeding when state.sqlite3 doesn't exist is a no-op (no crash)."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    # No state.sqlite3

    pattern = FailurePattern(
        id="test", description="", match_patterns=["x"],
        hint="fix", severity="minor",
    )
    # Should not raise
    _seed_operator_memory(str(tmp_path), [pattern])


def test_seed_handles_empty_patterns(db_with_table):
    """Seeding an empty list is a no-op."""
    _seed_operator_memory(str(db_with_table), [])
    # No crash = pass


def test_seed_multiple_patterns_same_batch(db_with_table, sample_patterns):
    """Both patterns in a batch are created."""
    _seed_operator_memory(str(db_with_table), sample_patterns)

    db_path = str(db_with_table / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)
    all_pats = om.list_all()
    assert len(all_pats) == 2


# ---------------------------------------------------------------------------
# _check_operator_memory (inbox_watch hook)
# ---------------------------------------------------------------------------

def test_check_operator_memory_no_state_db(tmp_path, capsys):
    """Missing state.sqlite3 — returns early, no output."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    from superharness.commands.inbox_watch import _check_operator_memory

    _check_operator_memory(str(tmp_path))
    captured = capsys.readouterr()
    assert captured.out == ""


def test_check_operator_memory_empty_inbox(db_with_table, capsys):
    """Empty inbox — no patterns logged."""
    from superharness.commands.inbox_watch import _check_operator_memory

    _check_operator_memory(str(db_with_table))
    captured = capsys.readouterr()
    assert "operator-memory:" not in captured.out


def test_check_operator_memory_handles_missing_state_reader(db_with_table, monkeypatch, capsys):
    """If get_inbox_items fails, the hook catches the exception and returns."""
    def _raise(*a, **kw):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(
        "superharness.engine.state_reader.get_inbox_items",
        _raise,
    )
    from superharness.commands.inbox_watch import _check_operator_memory

    # Should not raise
    _check_operator_memory(str(db_with_table))
    captured = capsys.readouterr()
    assert "operator-memory:" not in captured.out
