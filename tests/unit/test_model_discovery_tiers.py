"""Tests for per-tier cache keying (follow-up to PLAN-dynamic-model-selection).

The model-discovery cache was keyed (project, agent, auth_mode) holding ONE
model — after a mini probe cached gpt-5.4, a max request also returned
gpt-5.4.  With per-tier keying the cache holds (project, agent, auth_mode,
tier) so each tier resolves its own model.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine.db import CURRENT_SCHEMA_VERSION, init_db
from superharness.engine.model_discovery import DiscoveredModel, ModelDiscoveryCache
from superharness.engine.model_router import (
    _discover_for_agent,
    _model_discovery_cache_path,
    detect_auth_mode_for_agent,
    resolve_model_for_tier,
)
from superharness.engine import model_router


def _m(id: str, auth_mode: str = "chatgpt") -> DiscoveredModel:
    return DiscoveredModel(
        id=id, label=id, source="probe", auth_mode=auth_mode,
        probed_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Unit — per-tier CRUD
# ---------------------------------------------------------------------------


def test_set_get_distinct_tiers(tmp_path: Path) -> None:
    """Unit: mini and max entries coexist under one (project, agent, auth)."""
    db = tmp_path / "state.sqlite3"
    cache = ModelDiscoveryCache(db)
    cache.set("p", "codex-cli", _m("gpt-5.4"), tier="mini")
    cache.set("p", "codex-cli", _m("gpt-5.5"), tier="max")

    assert cache.get("p", "codex-cli", "chatgpt", tier="mini").id == "gpt-5.4"
    assert cache.get("p", "codex-cli", "chatgpt", tier="max").id == "gpt-5.5"


def test_get_missing_tier_returns_none(tmp_path: Path) -> None:
    """Unit: a tier with no entry reads as miss."""
    cache = ModelDiscoveryCache(tmp_path / "state.sqlite3")
    cache.set("p", "codex-cli", _m("gpt-5.4"), tier="mini")
    assert cache.get("p", "codex-cli", "chatgpt", tier="standard") is None


def test_default_tier_any_backward_compat(tmp_path: Path) -> None:
    """Unit: set/get without tier use 'any' — pre-upgrade callers still work."""
    cache = ModelDiscoveryCache(tmp_path / "state.sqlite3")
    cache.set("p", "codex-cli", _m("gpt-5.4"))
    assert cache.get("p", "codex-cli", "chatgpt").id == "gpt-5.4"


# ---------------------------------------------------------------------------
# Integration — migration v38
# ---------------------------------------------------------------------------


def test_migration_v38_lands_on_fresh_bootstrap(tmp_path: Path) -> None:
    """Integration: fresh init_db has the tier column + current version."""
    conn = sqlite3.connect(tmp_path / "state.sqlite3")
    try:
        init_db(conn, str(tmp_path))
        assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION
        cols = {r[1] for r in conn.execute("PRAGMA table_info(model_discovery)")}
        assert "tier" in cols
    finally:
        conn.close()


def test_migration_v38_upgrades_v37_rows(tmp_path: Path) -> None:
    """Integration: v37 rows (no tier) survive the upgrade with tier='any'."""
    conn = sqlite3.connect(tmp_path / "state.sqlite3")
    try:
        # Build a v37-shaped table with one row.
        conn.execute(
            """
            CREATE TABLE model_discovery (
                project_id  TEXT NOT NULL,
                agent       TEXT NOT NULL,
                model_id    TEXT NOT NULL,
                label       TEXT,
                source      TEXT NOT NULL DEFAULT 'probe',
                auth_mode   TEXT NOT NULL DEFAULT 'unknown',
                probed_at   TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL DEFAULT 86400,
                created_at  TEXT NOT NULL,
                PRIMARY KEY (project_id, agent, auth_mode)
            )
            """
        )
        conn.execute(
            "INSERT INTO model_discovery VALUES ('p','codex-cli','gpt-5.4','gpt-5.4','probe','chatgpt',?,86400,?)",
            (datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
        conn.execute("PRAGMA user_version = 37")
        conn.commit()

        init_db(conn, str(tmp_path))
        cache = ModelDiscoveryCache(tmp_path / "state.sqlite3")
        got = cache.get("p", "codex-cli", "chatgpt")  # default tier='any'
        assert got is not None and got.id == "gpt-5.4"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Integration — resolution honors tiers
# ---------------------------------------------------------------------------


def test_resolution_returns_distinct_per_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Integration: cached mini + max resolve to their own models."""
    db = tmp_path / "state.sqlite3"
    cache = ModelDiscoveryCache(db)
    cache.set(str(tmp_path), "codex-cli", _m("gpt-5.4"), tier="mini")
    cache.set(str(tmp_path), "codex-cli", _m("gpt-5.5"), tier="max")

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    monkeypatch.setattr(model_router, "_discover_for_agent", lambda a, m="unknown", c=None: [])

    assert resolve_model_for_tier("codex-cli", "mini", str(tmp_path)) == "gpt-5.4"
    assert resolve_model_for_tier("codex-cli", "max", str(tmp_path)) == "gpt-5.5"


def test_resolution_caches_discovered_per_tier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Integration: a discovered model is cached under the requested tier."""
    db = tmp_path / "state.sqlite3"
    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    monkeypatch.setattr(
        model_router,
        "_discover_for_agent",
        lambda a, m="unknown", c=None: [_m("gpt-5.4")],
    )

    resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    cache = ModelDiscoveryCache(db)
    assert cache.get(str(tmp_path), "codex-cli", "chatgpt", tier="mini").id == "gpt-5.4"


# ---------------------------------------------------------------------------
# Regression — probe/dashboard/doctor read path unchanged shape
# ---------------------------------------------------------------------------


def test_adapters_probe_uses_any_tier_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: adapters --probe (tier-less) reads the 'any' tier entry."""
    db = tmp_path / "state.sqlite3"
    cache = ModelDiscoveryCache(db)
    cache.set(str(tmp_path), "codex-cli", _m("gpt-5.4"), tier="any")

    from superharness.commands.adapters import _probe_available_models

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    monkeypatch.setattr(model_router, "_discover_for_agent", lambda a, m="unknown", c=None: [])

    result = _probe_available_models(str(tmp_path))
    assert result["codex-cli"] == ["gpt-5.4"]
