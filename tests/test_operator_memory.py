"""Tests for operator_memory.py — failure pattern memory for the watcher operator."""

from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Helper: in-memory SQLite path for tests
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db_path(tmp_path):
    """Return an in-memory -> file sqlite path in a tmp dir."""
    db = tmp_path / "state.sqlite3"
    yield str(db)


def _now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Table creation
# ---------------------------------------------------------------------------

def test_ensure_table_creates_operator_memory_table(mem_db_path):
    """Table is created if it doesn't exist."""
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()

    import sqlite3
    conn = sqlite3.connect(mem_db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='operator_memory'")
    assert cursor.fetchone() is not None


def test_ensure_table_is_idempotent(mem_db_path):
    """Calling ensure_table twice doesn't fail."""
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.ensure_table()  # no error


# ---------------------------------------------------------------------------
# Schema: all expected columns
# ---------------------------------------------------------------------------

def test_operator_memory_schema_has_all_columns(mem_db_path):
    """Verify every expected column exists."""
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()

    import sqlite3
    conn = sqlite3.connect(mem_db_path)
    cursor = conn.execute("PRAGMA table_info('operator_memory')")
    cols = {row[1] for row in cursor.fetchall()}
    expected = {
        "id", "pattern_signature", "resolution", "confidence",
        "hit_count", "miss_count", "created_at", "last_used_at",
    }
    assert cols == expected


# ---------------------------------------------------------------------------
# find_pattern
# ---------------------------------------------------------------------------

def test_find_pattern_returns_none_for_unknown_signature(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()

    result = om.find_pattern("port_8080_stuck")
    assert result is None


def test_find_pattern_returns_match_for_known_signature(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("port_8080_stuck", "kill -9 $(lsof -ti:8080) && restart")

    result = om.find_pattern("port_8080_stuck")
    assert result is not None
    assert result["resolution"] == "kill -9 $(lsof -ti:8080) && restart"
    assert result["hit_count"] == 0
    assert result["miss_count"] == 0
    assert result["confidence"] == 0.5  # default initial confidence


def test_find_pattern_is_case_sensitive_signature(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("Port_8080_Stuck", "fix a")

    # Exact match required
    result = om.find_pattern("port_8080_stuck")
    assert result is None


# ---------------------------------------------------------------------------
# record_match
# ---------------------------------------------------------------------------

def test_record_match_increments_hit_count(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("timeout_import", "retry with increased timeout")

    om.record_match("timeout_import", success=True)
    result = om.find_pattern("timeout_import")
    assert result["hit_count"] == 1
    assert result["miss_count"] == 0


def test_record_match_increments_miss_count(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("timeout_import", "retry with increased timeout")

    om.record_match("timeout_import", success=False)
    result = om.find_pattern("timeout_import")
    assert result["miss_count"] == 1
    assert result["hit_count"] == 0


def test_record_match_raises_when_signature_not_found(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()

    with pytest.raises(ValueError, match="Unknown signature"):
        om.record_match("nonexistent", success=True)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def test_confidence_rises_with_hits(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("stuck_dash", "kill dash && restart")

    # Default confidence is 0.5
    # hit_count=0, miss_count=0, total=0 → confidence stays 0.5

    om.record_match("stuck_dash", success=True)
    # hit=1, miss=0, total=1 → confidence = 1.0
    result = om.find_pattern("stuck_dash")
    assert result["confidence"] == 1.0


def test_confidence_drops_with_misses(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("stuck_dash", "kill dash && restart")

    om.record_match("stuck_dash", success=False)
    result = om.find_pattern("stuck_dash")
    assert result["confidence"] == 0.0


def test_confidence_balanced_with_mixed(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("mixed_signal", "fix something")

    om.record_match("mixed_signal", success=True)
    om.record_match("mixed_signal", success=True)
    om.record_match("mixed_signal", success=False)
    # hit=2, miss=1 → confidence = 2/3 ≈ 0.667
    result = om.find_pattern("mixed_signal")
    assert result["confidence"] == pytest.approx(0.667, abs=0.01)


# ---------------------------------------------------------------------------
# record_new
# ---------------------------------------------------------------------------

def test_record_new_stores_entry_with_defaults(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("disk_full", "clean up tmp")

    result = om.find_pattern("disk_full")
    assert result["pattern_signature"] == "disk_full"
    assert result["resolution"] == "clean up tmp"
    assert result["confidence"] == 0.5
    assert result["hit_count"] == 0
    assert result["miss_count"] == 0
    assert result["id"] is not None
    assert result["created_at"] is not None
    assert result["last_used_at"] is not None


def test_record_new_duplicate_raises_error(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("disk_full", "clean up tmp")

    with pytest.raises(ValueError, match="already exists"):
        om.record_new("disk_full", "different fix")


# ---------------------------------------------------------------------------
# forget
# ---------------------------------------------------------------------------

def test_forget_removes_entry(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("transient", "ignore")

    om.forget("transient")
    assert om.find_pattern("transient") is None


def test_forget_nonexistent_is_noop(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    # should not raise
    om.forget("nonexistent")


# ---------------------------------------------------------------------------
# list_all
# ---------------------------------------------------------------------------

def test_list_all_returns_all_patterns(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("a", "fix a")
    om.record_new("b", "fix b")

    results = om.list_all()
    assert len(results) == 2
    sigs = {r["pattern_signature"] for r in results}
    assert "a" in sigs and "b" in sigs


def test_list_all_empty_table(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()

    results = om.list_all()
    assert results == []


# ---------------------------------------------------------------------------
# prune_stale — removes low-confidence entries
# ---------------------------------------------------------------------------

def test_prune_stale_removes_low_confidence_entries(mem_db_path):
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("good", "fix")
    om.record_new("bad", "fix")
    om.record_new("mixed", "fix")

    # Make "bad" have low confidence
    om.record_match("bad", success=False)
    om.record_match("bad", success=False)
    # hit=0, miss=2 → confidence 0.0

    # Make "good" have high confidence
    om.record_match("good", success=True)
    om.record_match("good", success=True)
    # hit=2, miss=0 → confidence 1.0

    # "mixed" stays at 0.5

    removed = om.prune_stale(threshold=0.3)
    assert removed == 1  # only "bad" removed

    remaining = {r["pattern_signature"] for r in om.list_all()}
    assert "good" in remaining
    assert "mixed" in remaining
    assert "bad" not in remaining


# ---------------------------------------------------------------------------
# past_iso helper for tests that need stale timing
# ---------------------------------------------------------------------------

def test_find_pattern_with_high_confidence(mem_db_path):
    """When confidence >= 0.8, find_pattern returns the entry and last_used_at is updated."""
    from superharness.engine.operator_memory import OperatorMemory

    om = OperatorMemory(mem_db_path)
    om.ensure_table()
    om.record_new("known_fix", "restart service")

    # Build up high confidence
    for _ in range(5):
        om.record_match("known_fix", success=True)
    # 5 hits / 5 total → confidence 1.0

    result = om.find_pattern("known_fix")
    assert result is not None
    assert result["confidence"] >= 0.8
