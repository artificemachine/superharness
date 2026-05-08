"""Fix C — operator memory learns from unknown failures via a stable
hash signature derived from the error_snippet.

The original behavior had two failure modes:
1. _seed_operator_memory only fired on matched patterns, so unclassified
   errors (the dominant category in production: 5126/5126) never produced
   memory entries.
2. _learn_from_recovery and _check_operator_memory explicitly skipped
   pid == 'unknown', so the learning subsystem was structurally blind
   to repeated environmental failures.
"""
from __future__ import annotations

from superharness.engine.failure_patterns import (
    record_failure,
    unknown_signature,
)
from superharness.engine.operator_memory import OperatorMemory
from superharness.engine.db import get_connection, init_db


def _setup(tmp_path):
    project = tmp_path / "proj"
    (project / ".superharness").mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn, str(project))
    conn.commit()
    conn.close()
    return str(project)


def test_unknown_signature_is_stable_for_same_snippet():
    a = unknown_signature("Discussion directory not found: /tmp/x")
    b = unknown_signature("Discussion directory not found: /tmp/x")
    assert a == b
    assert a.startswith("unknown:")
    assert len(a) > len("unknown:")


def test_unknown_signature_differs_for_different_snippets():
    a = unknown_signature("Discussion directory not found")
    b = unknown_signature("Some other unrelated error")
    assert a != b


def test_record_failure_seeds_unknown_signature_when_no_pattern_matches(tmp_path):
    """The error 'Discussion directory not found' doesn't match any
    builtin pattern. Memory should still pick it up via the unknown
    signature so the watcher can detect it later."""
    project = _setup(tmp_path)
    snippet = "Discussion directory not found: /tmp/foo"

    matched = record_failure(project, "task-x", snippet, agent="claude-code")
    assert matched == []  # confirms no builtin pattern hit

    db_path = f"{project}/.superharness/state.sqlite3"
    om = OperatorMemory(db_path)
    om.ensure_table()
    sig = unknown_signature(snippet)
    entry = om.find_pattern(sig)
    assert entry is not None
    assert entry["resolution"]  # non-empty resolution hint


def test_record_failure_dedups_repeated_unknown_signature(tmp_path):
    """Repeated identical unknown failures share the same signature —
    the memory entry should exist exactly once."""
    project = _setup(tmp_path)
    snippet = "Some weird unmatched error"

    for _ in range(5):
        record_failure(project, "task-y", snippet, agent="claude-code")

    db_path = f"{project}/.superharness/state.sqlite3"
    om = OperatorMemory(db_path)
    om.ensure_table()
    sig = unknown_signature(snippet)
    entries = [e for e in om.list_all() if e["pattern_signature"] == sig]
    assert len(entries) == 1
