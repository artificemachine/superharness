"""End-to-end test: operator memory full lifecycle.

Simulates the complete cycle:
  1. Task fails → failure_patterns.record_failure() matches patterns
  2. Patterns are seeded into operator_memory via _seed_operator_memory
  3. Watcher's _check_operator_memory finds patterns, logs misses on retry
  4. Operator calls record_match(success=True) after recovery → confidence rises
  5. Next cycle: high-confidence patterns surface fix hints
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from superharness.engine.failure_patterns import match_patterns, record_failure
from superharness.engine.operator_memory import OperatorMemory


# ---------------------------------------------------------------------------
# Fixtures — full project bootstrap
# ---------------------------------------------------------------------------

@pytest.fixture
def e2e_project(tmp_path):
    """Create a temp project with SQLite + operator_memory table + sample task."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "handoffs").mkdir()

    # Init SQLite (same as _bootstrap in blackbox tests)
    from superharness.engine.db import get_connection, init_db
    conn = get_connection(str(tmp_path))
    init_db(conn)
    conn.close()

    # Ensure operator_memory table exists
    db_path = str(sh / "state.sqlite3")
    om = OperatorMemory(db_path)
    om.ensure_table()

    return tmp_path


# ---------------------------------------------------------------------------
# Phase 1: Failure → pattern match → seed
# ---------------------------------------------------------------------------

def test_e2e_failure_seeds_operator_memory(e2e_project):
    """record_failure() matches patterns and seeds operator_memory."""
    error_text = "ModuleNotFoundError: No module named 'requests'"

    matched = record_failure(str(e2e_project), "task-1", error_text)
    ids = [p.id for p in matched]
    assert "import_error" in ids

    # Verify operator_memory was seeded
    db_path = str(e2e_project / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)
    mem = om.find_pattern("import_error")
    assert mem is not None
    assert mem["confidence"] == 0.5
    assert mem["hit_count"] == 0
    assert mem["miss_count"] == 0


def test_e2e_unknown_error_seeds_via_hash_signature(e2e_project):
    """Unmatched errors seed memory under a stable unknown:<hash>
    signature derived from the error_snippet. This lets the watcher
    learn from repeated environmental failures (missing dirs, missing
    CLIs) that the regex library doesn't classify."""
    from superharness.engine.failure_patterns import unknown_signature
    error_text = "Something completely unrecognizable XYZ-12345"

    matched = record_failure(str(e2e_project), "task-2", error_text)
    assert not matched  # no builtin pattern matches

    db_path = str(e2e_project / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)
    sig = unknown_signature(error_text)
    entry = om.find_pattern(sig)
    assert entry is not None
    assert entry["pattern_signature"].startswith("unknown:")


# ---------------------------------------------------------------------------
# Phase 2: Confidence tracking — hits and misses
# ---------------------------------------------------------------------------

def test_e2e_confidence_rises_with_successful_recovery(e2e_project):
    """After failure → seed → successful recovery → confidence rises."""
    db_path = str(e2e_project / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)

    # Simulate: failure recorded, pattern seeded
    record_failure(str(e2e_project), "task-3",
                   "PermissionError: [Errno 13] Permission denied")
    assert om.find_pattern("permission_denied") is not None

    # Simulate: recovery works — record hit
    om.record_match("permission_denied", success=True)
    result = om.find_pattern("permission_denied")
    assert result["hit_count"] == 1
    assert result["miss_count"] == 0
    assert result["confidence"] == 1.0


def test_e2e_confidence_drops_with_repeated_failures(e2e_project):
    """Repeated misses drive confidence below prune threshold."""
    db_path = str(e2e_project / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)

    record_failure(str(e2e_project), "task-4",
                   "TimeoutError: operation timed out")
    assert om.find_pattern("timeout") is not None

    # Simulate: 3 failed retries
    for _ in range(3):
        om.record_match("timeout", success=False)

    result = om.find_pattern("timeout")
    assert result["miss_count"] == 3
    assert result["hit_count"] == 0
    assert result["confidence"] == 0.0

    # Should be pruned
    removed = om.prune_stale(threshold=0.3)
    assert removed == 1
    assert om.find_pattern("timeout") is None


# ---------------------------------------------------------------------------
# Phase 3: Multiple patterns, mixed confidence
# ---------------------------------------------------------------------------

def test_e2e_multiple_failures_mixed_confidence(e2e_project):
    """Multiple failures produce multiple patterns with independent confidence."""
    db_path = str(e2e_project / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)

    # Failure #1: import error — fixed immediately
    record_failure(str(e2e_project), "task-5",
                   "ModuleNotFoundError: No module named 'pydantic'")
    om.record_match("import_error", success=True)

    # Failure #2: permission denied — keeps failing
    record_failure(str(e2e_project), "task-6",
                   "PermissionError: [Errno 13] Permission denied")
    om.record_match("permission_denied", success=False)
    om.record_match("permission_denied", success=False)

    # Failure #3: import error again — still works
    record_failure(str(e2e_project), "task-7",
                   "ModuleNotFoundError: No module named 'numpy'")
    om.record_match("import_error", success=True)

    # Verify independent confidence
    imp_err = om.find_pattern("import_error")
    perm_den = om.find_pattern("permission_denied")

    assert imp_err["hit_count"] == 2
    assert imp_err["confidence"] == 1.0

    assert perm_den["hit_count"] == 0
    assert perm_den["miss_count"] == 2
    assert perm_den["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Phase 4: forget and re-learn
# ---------------------------------------------------------------------------

def test_e2e_forget_and_relearn(e2e_project):
    """Forgetting a pattern and re-seeding starts fresh."""
    db_path = str(e2e_project / ".superharness" / "state.sqlite3")
    om = OperatorMemory(db_path)

    # Seed with bad confidence
    record_failure(str(e2e_project), "task-8",
                   "SyntaxError: invalid syntax")
    om.record_match("syntax_error", success=False)
    om.record_match("syntax_error", success=False)

    assert om.find_pattern("syntax_error")["confidence"] == 0.0

    # Forget it
    om.forget("syntax_error")
    assert om.find_pattern("syntax_error") is None

    # Re-learn from a new failure
    record_failure(str(e2e_project), "task-9",
                   "SyntaxError: invalid syntax in foo.py")
    fresh = om.find_pattern("syntax_error")
    assert fresh is not None
    assert fresh["confidence"] == 0.5
    assert fresh["hit_count"] == 0
    assert fresh["miss_count"] == 0
