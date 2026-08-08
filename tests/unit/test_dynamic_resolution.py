"""Tests for Iteration 5 of PLAN-dynamic-model-selection.md.

Covers:
- `resolve_model_for_tier()` — cache-first, accept-chain matching, auth-aware
- `resolve_model()` kept as a thin wrapper (regression)
- `detect_auth_mode_for_agent()` — per-agent auth detection, cached
- Auth-flip invalidation (state machine)
- End-to-end: fake codex rejects mini, accepts fallback → dispatch lands
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine import model_router
from superharness.engine.model_discovery import DiscoveredModel, ModelDiscoveryCache
from superharness.engine.model_router import (
    detect_auth_mode_for_agent,
    resolve_model,
    resolve_model_for_tier,
    reset_auth_mode_cache,
)


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_resolve_returns_nonempty_for_all_adapters() -> None:
    """Smoke: resolve_model_for_tier returns a non-empty string per adapter."""
    for adapter in ("claude-code", "codex-cli", "gemini-cli", "opencode"):
        for tier in ("mini", "standard", "max"):
            m = resolve_model_for_tier(adapter, tier)
            assert isinstance(m, str) and m


# ---------------------------------------------------------------------------
# Unit — resolution priority
# ---------------------------------------------------------------------------


def test_cache_hit_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Unit: a cached model is returned without discovery."""
    db = tmp_path / "state.sqlite3"
    cache = ModelDiscoveryCache(db)
    cache.set(
        str(tmp_path),
        "codex-cli",
        DiscoveredModel("gpt-5-codex-mini", "gpt-5-codex-mini", "probe", "chatgpt", datetime.now(timezone.utc)),
        tier="mini",
    )

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    calls: list[str] = []
    monkeypatch.setattr(
        model_router,
        "_discover_for_agent",
        lambda a, m="unknown", c=None: calls.append(a) or [],
    )
    assert resolve_model_for_tier("codex-cli", "mini", str(tmp_path)) == "gpt-5-codex-mini"
    assert calls == []  # no discovery ran


def test_discovery_success_uses_accept_chain_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unit: on cache miss, discovery + accept-chain pick the working model."""
    db = tmp_path / "state.sqlite3"
    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")

    # Discovery returns a model that is NOT the manifest preferred but IS in
    # the accept chain — the chain match must win.
    def _fake_discover(agent, auth_mode="unknown", chain=None):
        return [
            DiscoveredModel("gpt-5-codex-mini", "gpt-5-codex-mini", "probe", auth_mode, datetime.now(timezone.utc))
        ]

    monkeypatch.setattr(model_router, "_discover_for_agent", _fake_discover)
    resolved = resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    assert resolved == "gpt-5-codex-mini"

    # And it was cached for the next call, under the requested tier.
    cache = ModelDiscoveryCache(db)
    cached = cache.get(str(tmp_path), "codex-cli", "chatgpt", tier="mini")
    assert cached is not None and cached.id == "gpt-5-codex-mini"


def test_discovery_failure_falls_back_to_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unit: discovery failure → manifest preferred (legacy resolve_model)."""
    db = tmp_path / "state.sqlite3"
    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    monkeypatch.setattr(model_router, "_discover_for_agent", lambda a, m="unknown", c=None: [])

    # Manifest preferred for codex-cli mini is gpt-5.1-codex-mini (legacy
    # schema still in the bundled manifest at this iteration).
    resolved = resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    assert resolved == "gpt-5.1-codex-mini"


# ---------------------------------------------------------------------------
# Regression — resolve_model stays a thin wrapper
# ---------------------------------------------------------------------------


def test_resolve_model_still_works_as_wrapper(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression: resolve_model() remains callable and returns a model."""
    m = resolve_model("codex-cli", "mini")
    assert isinstance(m, str) and m


# ---------------------------------------------------------------------------
# Contract — auth detection
# ---------------------------------------------------------------------------


def test_detect_auth_mode_returns_known_values() -> None:
    """Contract: auth detection returns one of chatgpt/apikey/unknown."""
    reset_auth_mode_cache()
    mode = detect_auth_mode_for_agent("codex-cli")
    assert mode in ("chatgpt", "apikey", "unknown")


def test_detect_auth_mode_unknown_for_unprobed_agent() -> None:
    """Contract: agents without auth detection return 'unknown'."""
    assert detect_auth_mode_for_agent("gemini-cli") == "unknown"


# ---------------------------------------------------------------------------
# State machine — auth flip invalidates cache
# ---------------------------------------------------------------------------


def test_auth_flip_reprobes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """State machine: auth flip → old-mode cache ignored, new mode probed."""
    db = tmp_path / "state.sqlite3"
    cache = ModelDiscoveryCache(db)
    # Cache holds a chatgpt-mode entry.
    cache.set(
        str(tmp_path),
        "codex-cli",
        DiscoveredModel("gpt-5-codex-mini", "gpt-5-codex-mini", "probe", "chatgpt", datetime.now(timezone.utc)),
        tier="mini",
    )

    # Auth flips to apikey; discovery returns an apikey model.
    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "apikey")

    def _fake_discover(agent, auth_mode="unknown", chain=None):
        return [
            DiscoveredModel("gpt-5.1-codex-mini", "gpt-5.1-codex-mini", "probe", auth_mode, datetime.now(timezone.utc))
        ]

    monkeypatch.setattr(model_router, "_discover_for_agent", _fake_discover)
    resolved = resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    # apikey mode must NOT return the chatgpt cached model.
    assert resolved == "gpt-5.1-codex-mini"

    # The apikey entry is now cached under its own auth key + tier.
    cached_apikey = cache.get(str(tmp_path), "codex-cli", "apikey", tier="mini")
    assert cached_apikey is not None and cached_apikey.id == "gpt-5.1-codex-mini"
    # The chatgpt entry is untouched (invalidation is per-agent+mode+tier).
    cached_chatgpt = cache.get(str(tmp_path), "codex-cli", "chatgpt", tier="mini")
    assert cached_chatgpt is not None and cached_chatgpt.id == "gpt-5-codex-mini"


# ---------------------------------------------------------------------------
# Chaos — cache corruption
# ---------------------------------------------------------------------------


def test_chaos_unknown_agent_discovery_returns_empty() -> None:
    """Chaos: _discover_for_agent on an unregistered harness returns []."""
    from superharness.engine.model_router import _discover_for_agent

    assert _discover_for_agent("no-such-harness") == []


def test_chaos_cache_read_failure_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chaos: cache read raising sqlite error → falls through to discovery."""
    from superharness.engine.model_router import _model_discovery_cache_path

    def _broken_cache_path(project_dir):
        # A path whose directory is actually a file → sqlite3.Error on open.
        blocker = tmp_path / "blocker"
        blocker.write_text("x")
        return str(blocker)

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", _broken_cache_path)
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    monkeypatch.setattr(
        model_router,
        "_discover_for_agent",
        lambda agent, auth_mode="unknown", chain=None: [
            DiscoveredModel("m1", "m1", "probe", auth_mode, datetime.now(timezone.utc))
        ],
    )
    resolved = resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    assert resolved == "m1"


def test_chaos_accept_chain_unknown_adapter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chaos: _tier_accept_chain on an unknown adapter returns [] (no raise)."""
    from superharness.engine.model_router import _tier_accept_chain

    assert _tier_accept_chain("no-such-adapter", "mini", "chatgpt") == []


def test_chaos_corrupt_cache_skipped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Chaos: corrupt cache row (bad JSON-ish timestamp) → silent skip, no raise."""
    db = tmp_path / "state.sqlite3"
    cache = ModelDiscoveryCache(db)
    cache.set(
        str(tmp_path),
        "codex-cli",
        DiscoveredModel("good", "good", "probe", "chatgpt", datetime.now(timezone.utc)),
    )
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT OR REPLACE INTO model_discovery "
        "(project_id, agent, tier, model_id, label, source, auth_mode, probed_at, ttl_seconds, created_at) "
        "VALUES (?, ?, 'any', 'bad', 'bad', 'probe', 'chatgpt', 'not-a-date', 3600, ?)",
        (str(tmp_path), "codex-cli", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(model_router, "_model_discovery_cache_path", lambda p: str(db))
    monkeypatch.setattr(model_router, "detect_auth_mode_for_agent", lambda a: "chatgpt")
    monkeypatch.setattr(model_router, "_discover_for_agent", lambda a, m="unknown", c=None: [])
    # Must not raise; falls through to manifest.
    resolved = resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    assert resolved == "gpt-5.1-codex-mini"


# ---------------------------------------------------------------------------
# E2E — fake codex rejects mini, accepts fallback → dispatch lands
# ---------------------------------------------------------------------------


@pytest.mark.skipif(sys.platform == "win32", reason="fake-codex shim requires bash")
def test_e2e_fake_codex_dispatch_lands_on_working_model(tmp_path: Path) -> None:
    """E2E: full resolution with a fake codex that rejects the hardcoded
    mini model and accepts the fallback — the working model must be picked.

    Uses a real ProbeDiscovery path through the harness, caching the result.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "#!/bin/bash\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$arg\" = 'gpt-5.1-codex-mini' ]; then\n"
        "    echo 'model is not supported' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "done\n"
        "echo ok\n"
    )
    fake_codex.chmod(0o755)

    # The probe harness runs `codex exec --model X ...`; put the fake on PATH.
    import os
    import subprocess

    from superharness.engine.probe_discovery import ProbeDiscovery

    p = ProbeDiscovery(
        "codex-cli",
        ["gpt-5.1-codex-mini", "gpt-5.3-codex"],
        "chatgpt",
        budget_seconds=30,
        bin_path=str(fake_codex),
    )
    found = p.run()
    assert [m.id for m in found] == ["gpt-5.3-codex"]
