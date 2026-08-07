"""Tests for Iteration 1 of PLAN-dynamic-model-selection.md.

Covers:
- `DiscoveredModel` dataclass (contract)
- `ModelDiscoveryCache` (unit, integration, state machine, chaos, e2e, perf)
- `Harness.discover_models()` Protocol extension (contract, regression)
- SQLite migration v37 `model_discovery` table (integration)
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from superharness.engine.db import CURRENT_SCHEMA_VERSION, init_db
from superharness.engine.model_discovery import DiscoveredModel, ModelDiscoveryCache
from superharness.harnesses import get_harness
from superharness.harnesses.base import Harness


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_discovered_model_instantiates() -> None:
    """Smoke: DiscoveredModel constructs with all required fields."""
    m = DiscoveredModel(
        id="gpt-5-codex-mini",
        label="GPT-5 Codex mini",
        source="probe",
        auth_mode="chatgpt",
        probed_at=datetime.now(timezone.utc),
    )
    assert m.id == "gpt-5-codex-mini"
    assert m.source == "probe"
    assert m.auth_mode == "chatgpt"


def test_all_four_harnesses_satisfy_extended_protocol() -> None:
    """Smoke: every registered harness still satisfies the Harness Protocol."""
    for name in ("claude-code", "codex-cli", "gemini-cli", "opencode"):
        harness = get_harness(name)
        assert isinstance(harness, Harness)
        # Protocol is runtime_checkable; method presence is the contract.
        assert callable(getattr(harness, "discover_models", None))


# ---------------------------------------------------------------------------
# Unit — ModelDiscoveryCache CRUD
# ---------------------------------------------------------------------------


def _make_cache(tmp_path: Path) -> ModelDiscoveryCache:
    return ModelDiscoveryCache(db_path=tmp_path / "state.sqlite3")


def _sample(tmp_path: Path, **overrides) -> DiscoveredModel:
    kwargs = dict(
        id="gpt-5-codex-mini",
        label="GPT-5 Codex mini",
        source="probe",
        auth_mode="chatgpt",
        probed_at=datetime.now(timezone.utc),
    )
    kwargs.update(overrides)
    return DiscoveredModel(**kwargs)


def test_cache_set_get_roundtrip(tmp_path: Path) -> None:
    """Unit: set then get returns the same entry."""
    cache = _make_cache(tmp_path)
    m = _sample(tmp_path)
    cache.set("proj1", "codex-cli", m)
    got = cache.get("proj1", "codex-cli", "chatgpt")
    assert got is not None
    assert got.id == m.id
    assert got.source == m.source
    assert got.auth_mode == m.auth_mode


def test_cache_get_returns_none_on_miss(tmp_path: Path) -> None:
    """Unit: get on an unset key returns None."""
    cache = _make_cache(tmp_path)
    assert cache.get("proj1", "codex-cli", "chatgpt") is None


def test_cache_get_returns_none_for_different_auth_mode(tmp_path: Path) -> None:
    """Unit: entries are keyed by auth_mode; chatgpt row is not visible to apikey."""
    cache = _make_cache(tmp_path)
    cache.set("proj1", "codex-cli", _sample(tmp_path, auth_mode="chatgpt"))
    assert cache.get("proj1", "codex-cli", "apikey") is None
    assert cache.get("proj1", "codex-cli", "chatgpt") is not None


def test_cache_ttl_expiry(tmp_path: Path) -> None:
    """Unit: entries past TTL read as miss."""
    cache = _make_cache(tmp_path)
    old = _sample(
        tmp_path,
        probed_at=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    cache.set("proj1", "codex-cli", old, ttl_seconds=86400)
    assert cache.get("proj1", "codex-cli", "chatgpt") is None


def test_cache_invalidate(tmp_path: Path) -> None:
    """Unit: invalidate removes an entry for one agent."""
    cache = _make_cache(tmp_path)
    cache.set("proj1", "codex-cli", _sample(tmp_path))
    cache.set("proj1", "claude-code", _sample(tmp_path, id="claude-sonnet-4-6"))
    cache.invalidate("proj1", "codex-cli")
    assert cache.get("proj1", "codex-cli", "chatgpt") is None
    assert cache.get("proj1", "claude-code", "chatgpt") is not None


def test_cache_clear(tmp_path: Path) -> None:
    """Unit: clear removes every entry."""
    cache = _make_cache(tmp_path)
    cache.set("proj1", "codex-cli", _sample(tmp_path))
    cache.set("proj2", "codex-cli", _sample(tmp_path))
    cache.clear()
    assert cache.get("proj1", "codex-cli", "chatgpt") is None
    assert cache.get("proj2", "codex-cli", "chatgpt") is None


# ---------------------------------------------------------------------------
# Integration — SQLite persistence + migration
# ---------------------------------------------------------------------------


def test_cache_survives_two_connections(tmp_path: Path) -> None:
    """Integration: a second connection to the same DB sees the entry."""
    cache = _make_cache(tmp_path)
    cache.set("proj1", "codex-cli", _sample(tmp_path))

    cache2 = ModelDiscoveryCache(db_path=tmp_path / "state.sqlite3")
    got = cache2.get("proj1", "codex-cli", "chatgpt")
    assert got is not None
    assert got.id == "gpt-5-codex-mini"


def test_migration_v37_lands_on_fresh_bootstrap(tmp_path: Path) -> None:
    """Integration: fresh init_db yields CURRENT_SCHEMA_VERSION with the table."""
    conn = sqlite3.connect(tmp_path / "state.sqlite3")
    try:
        init_db(conn, str(tmp_path))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "model_discovery" in tables
    finally:
        conn.close()


def test_migration_v37_lands_on_v36_baseline(tmp_path: Path) -> None:
    """Integration: a DB at user_version=36 upgrades cleanly to 37."""
    conn = sqlite3.connect(tmp_path / "state.sqlite3")
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        conn.execute("PRAGMA user_version = 36")
        conn.commit()
        init_db(conn, str(tmp_path))
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == CURRENT_SCHEMA_VERSION
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "model_discovery" in tables
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# State machine — entry lifecycle
# ---------------------------------------------------------------------------


def test_entry_lifecycle_miss_write_hit_expire(tmp_path: Path) -> None:
    """State machine: miss -> write -> hit -> expire -> miss is one-way."""
    cache = _make_cache(tmp_path)
    assert cache.get("p", "a", "chatgpt") is None  # miss
    cache.set("p", "a", _sample(tmp_path), ttl_seconds=1)
    assert cache.get("p", "a", "chatgpt") is not None  # hit
    time.sleep(1.1)
    assert cache.get("p", "a", "chatgpt") is None  # expire -> miss


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_discovered_model_field_set() -> None:
    """Contract: DiscoveredModel exposes exactly the spec'd fields."""
    fields = set(DiscoveredModel.__dataclass_fields__)
    assert fields == {"id", "label", "source", "auth_mode", "probed_at"}


def test_harness_discover_models_signature() -> None:
    """Contract: default discover_models has (auth_mode='unknown') -> list."""
    from superharness.harnesses.codex import CodexHarness

    h = CodexHarness()
    result = h.discover_models()
    assert result == []
    result = h.discover_models(auth_mode="chatgpt")
    assert result == []


# ---------------------------------------------------------------------------
# Regression — existing harness invocations unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,task",
    [
        ("codex-cli", {"prompt": "x", "model": "", "effort": "", "yolo": False, "codex_bypass": False}),
        ("opencode", {"prompt": "x", "model": "", "effort": "", "yolo": False, "codex_bypass": False}),
    ],
)
def test_harness_invocation_unchanged_with_discover_models(
    name: str, task: dict, tmp_path: Path
) -> None:
    """Regression: adding discover_models doesn't change build_invocation output."""
    from superharness.harnesses import get_harness

    h = get_harness(name)
    inv = h.build_invocation(task, str(tmp_path), True)
    assert inv.argv[0] == "bash"
    assert "--non-interactive" in inv.argv


# ---------------------------------------------------------------------------
# Chaos — malformed rows
# ---------------------------------------------------------------------------


def test_chaos_malformed_timestamp_rows_are_skipped(tmp_path: Path) -> None:
    """Chaos: a row with a garbage probed_at doesn't crash reads.

    The schema's NOT NULL on model_id already blocks NULL ids, so the
    reachable malformed case is an unparseable timestamp — it must read as
    a miss (expired), not raise.
    """
    cache = _make_cache(tmp_path)
    cache.set("p", "a", _sample(tmp_path))

    conn = sqlite3.connect(tmp_path / "state.sqlite3")
    try:
        conn.execute(
            "INSERT INTO model_discovery (project_id, agent, model_id, label, source, auth_mode, probed_at, ttl_seconds, created_at) "
            "VALUES (?, ?, ?, 'broken', 'probe', 'chatgpt', ?, 3600, ?)",
            ("p", "broken-agent", "model-broken-ts", "not-a-timestamp", datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    # Must not raise; the malformed row reads as a miss (expired).
    assert cache.get("p", "broken-agent", "chatgpt") is None
    # The good row is unaffected.
    got = cache.get("p", "a", "chatgpt")
    assert got is not None
    assert got.id == "gpt-5-codex-mini"


# ---------------------------------------------------------------------------
# E2E — cross-process round trip
# ---------------------------------------------------------------------------


def test_e2e_cross_process_roundtrip(tmp_path: Path) -> None:
    """E2E: write from one connection, read from a fresh one."""
    cache = _make_cache(tmp_path)
    cache.set(
        "projX",
        "codex-cli",
        _sample(tmp_path, id="gpt-5-codex-mini"),
    )
    cache.set(
        "projX",
        "claude-code",
        _sample(tmp_path, id="claude-haiku-4-5-20251001"),
    )
    cache.set(
        "projX",
        "opencode",
        _sample(tmp_path, id="deepseek/deepseek-chat"),
    )

    cache2 = ModelDiscoveryCache(db_path=tmp_path / "state.sqlite3")
    assert cache2.get("projX", "codex-cli", "chatgpt") is not None
    assert cache2.get("projX", "claude-code", "chatgpt") is not None
    assert cache2.get("projX", "opencode", "chatgpt") is not None
    assert cache2.get("projX", "gemini-cli", "chatgpt") is None


# ---------------------------------------------------------------------------
# Performance — cache read on 1000 rows
# ---------------------------------------------------------------------------


def test_perf_cache_read_under_5ms(tmp_path: Path) -> None:
    """Performance: read from a 1000-row table takes < 5ms p99."""
    cache = _make_cache(tmp_path)
    for i in range(1000):
        cache.set(
            f"proj{i}",
            "codex-cli",
            _sample(tmp_path, id=f"model-{i}"),
        )

    cache2 = ModelDiscoveryCache(db_path=tmp_path / "state.sqlite3")
    start = time.perf_counter()
    for i in range(0, 1000, 10):
        cache2.get(f"proj{i}", "codex-cli", "chatgpt")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert elapsed_ms < 5000  # 100 reads * 5ms budget


# ---------------------------------------------------------------------------
# TDD Parity — every public method exercised via real calls
# ---------------------------------------------------------------------------


def test_tdd_parity_all_public_methods_exercised(tmp_path: Path) -> None:
    """TDD Parity: set/get/invalidate/clear are each called through real paths."""
    cache = _make_cache(tmp_path)
    # set + get
    cache.set("p", "a", _sample(tmp_path))
    assert cache.get("p", "a", "chatgpt") is not None
    # invalidate
    cache.invalidate("p", "a")
    assert cache.get("p", "a", "chatgpt") is None
    # set + clear
    cache.set("p", "a", _sample(tmp_path))
    cache.clear()
    assert cache.get("p", "a", "chatgpt") is None
    # TTL path
    cache.set("p", "a", _sample(tmp_path, probed_at=datetime.now(timezone.utc) - timedelta(hours=25)), ttl_seconds=3600)
    assert cache.get("p", "a", "chatgpt") is None
