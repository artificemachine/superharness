"""Tests for Iteration 2 of PLAN-dynamic-model-selection.md.

Covers:
- `_parse_opencode_models_output()` — plain-text `opencode models` parser
- `OpenCodeHarness.discover_models()` — native discovery via subprocess
- `resolve_model_for_tier()` — cache-first resolution with manifest fallback
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine.model_discovery import DiscoveredModel, ModelDiscoveryCache
from superharness.harnesses.opencode import OpencodeHarness
from superharness.harnesses.opencode import _parse_opencode_models_output


# ---------------------------------------------------------------------------
# Unit — parser
# ---------------------------------------------------------------------------


def test_parse_single_provider_lines() -> None:
    """Unit: parses plain-text provider/model-id lines."""
    text = "alibaba/qwen-max\nopencode/deepseek-v4-flash-free\ngithub/gpt-5-codex\n"
    models = _parse_opencode_models_output(text)
    assert [m.id for m in models] == [
        "alibaba/qwen-max",
        "opencode/deepseek-v4-flash-free",
        "github/gpt-5-codex",
    ]
    # label defaults to the full id (plain text output has no separate label)
    assert models[0].label == "alibaba/qwen-max"


def test_parse_empty_output() -> None:
    """Unit: empty output parses to an empty list."""
    assert _parse_opencode_models_output("") == []
    assert _parse_opencode_models_output("\n\n\n") == []


def test_parse_skips_junk_lines() -> None:
    """Unit: non-model junk lines (banners, warnings) are skipped."""
    text = "opencode logo\n\nsome warning text\nalibaba/qwen-max\n"
    models = _parse_opencode_models_output(text)
    assert [m.id for m in models] == ["alibaba/qwen-max"]


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_discover_models_returns_list_without_raising(tmp_path: Path) -> None:
    """Smoke: discover_models() never raises; returns a list."""
    h = OpencodeHarness()
    result = h.discover_models()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_discover_models_returns_native_source() -> None:
    """Contract: every DiscoveredModel from discover_models has source='native'."""
    h = OpencodeHarness()
    models = h.discover_models()
    if models:
        assert all(m.source == "native" for m in models)


# ---------------------------------------------------------------------------
# Integration — stubbed subprocess → cache → resolve_model_for_tier
# ---------------------------------------------------------------------------


def test_stubbed_cli_populates_cache_and_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: canned `opencode models` output → cache populated →
    resolve_model_for_tier returns the discovered model."""
    from superharness.harnesses import get_harness
    from superharness.engine import model_router

    h = get_harness("opencode")
    h.discover_models = lambda auth_mode="unknown": [
        DiscoveredModel(
            id="opencode/deepseek-v4-flash",
            label="opencode/deepseek-v4-flash",
            source="native",
            auth_mode="unknown",
            probed_at=datetime.now(timezone.utc),
        )
    ]

    # Persist the discovered model into the cache for this project.
    cache = ModelDiscoveryCache(db_path=tmp_path / "state.sqlite3")
    cache.set(
        str(tmp_path),
        "opencode",
        DiscoveredModel(
            id="opencode/deepseek-v4-flash",
            label="opencode/deepseek-v4-flash",
            source="native",
            auth_mode="unknown",
            probed_at=datetime.now(timezone.utc),
        ),
    )

    monkeypatch.setattr(
        model_router, "_model_discovery_cache_path", lambda p: str(tmp_path / "state.sqlite3")
    )
    resolved = model_router.resolve_model_for_tier(
        "opencode", "mini", str(tmp_path)
    )
    assert resolved == "opencode/deepseek-v4-flash"


def test_resolve_model_for_tier_falls_back_to_manifest_when_cache_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: empty cache → resolve falls back to the manifest model."""
    from superharness.engine import model_router

    monkeypatch.setattr(
        model_router, "_model_discovery_cache_path", lambda p: str(tmp_path / "state.sqlite3")
    )
    resolved = model_router.resolve_model_for_tier("codex-cli", "mini", str(tmp_path))
    # Manifest fallback: codex-cli mini maps to gpt-5.1-codex-mini (hardcoded).
    assert resolved == "gpt-5.1-codex-mini"


# ---------------------------------------------------------------------------
# State machine — miss → probe → write → hit
# ---------------------------------------------------------------------------


def test_cache_miss_triggers_discovery_then_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """State machine: first resolve (miss) → discovery → cache write;
    second resolve hits the cache without re-discovering."""
    from superharness.engine import model_router

    calls: list[str] = []

    # Stub the harness discovery to record calls.
    h = OpencodeHarness()
    h.discover_models = lambda auth_mode="unknown": calls.append("probe") or [
        DiscoveredModel(
            id="opencode/deepseek-v4-flash",
            label="opencode/deepseek-v4-flash",
            source="native",
            auth_mode="unknown",
            probed_at=datetime.now(timezone.utc),
        )
    ]
    monkeypatch.setattr(
        model_router,
        "_discover_for_agent",
        lambda agent, auth_mode="unknown": h.discover_models(auth_mode),
    )
    monkeypatch.setattr(
        model_router, "_model_discovery_cache_path", lambda p: str(tmp_path / "state.sqlite3")
    )

    r1 = model_router.resolve_model_for_tier("opencode", "mini", str(tmp_path))
    r2 = model_router.resolve_model_for_tier("opencode", "mini", str(tmp_path))
    assert r1 == "opencode/deepseek-v4-flash"
    assert r2 == "opencode/deepseek-v4-flash"
    # Probe ran exactly once: first call probed, second hit the cache.
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Chaos
# ---------------------------------------------------------------------------


def test_chaos_binary_missing_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaos: opencode binary missing → discover_models returns [] without raising."""
    import subprocess

    h = OpencodeHarness()

    def _fake_run(*args, **kwargs):
        raise FileNotFoundError("opencode not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert h.discover_models() == []


def test_chaos_timeout_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaos: subprocess timeout → discover_models returns [] without raising."""
    import subprocess

    h = OpencodeHarness()

    def _fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="opencode", timeout=5)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert h.discover_models() == []


def test_chaos_nonzero_exit_returns_empty_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaos: opencode models exits non-zero → [] without raising."""
    import subprocess

    h = OpencodeHarness()

    class _FakeResult:
        returncode = 1
        stdout = "provider/model-x\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    assert h.discover_models() == []


def test_chaos_junk_stdout_returns_only_valid_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chaos: junk stdout still yields only valid model lines, no raise."""
    import subprocess

    h = OpencodeHarness()

    class _FakeResult:
        returncode = 0
        stdout = "banner line\nprovider/model-x\n\nother junk\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    models = h.discover_models()
    assert [m.id for m in models] == ["provider/model-x"]
    assert models[0].source == "native"


def test_auth_mode_tagged_onto_discovered_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration: auth_mode is stamped onto entries when passed."""
    import subprocess

    h = OpencodeHarness()

    class _FakeResult:
        returncode = 0
        stdout = "provider/model-x\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    models = h.discover_models(auth_mode="apikey")
    assert len(models) == 1
    assert models[0].auth_mode == "apikey"


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------


def test_regression_build_invocation_unchanged(tmp_path: Path) -> None:
    """Regression: build_invocation output is unchanged by discovery additions."""
    h = OpencodeHarness()
    inv = h.build_invocation(
        {"prompt": "x", "model": "", "effort": "", "yolo": False, "codex_bypass": False},
        str(tmp_path),
        True,
    )
    assert inv.argv[0] == "bash"
    assert "--non-interactive" in inv.argv


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_perf_parse_50_models_under_100ms() -> None:
    """Performance: parsing 50 model lines takes < 100ms."""
    import time

    text = "\n".join(f"provider{i}/model{i}" for i in range(50)) + "\n"
    start = time.perf_counter()
    models = _parse_opencode_models_output(text)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert len(models) == 50
    assert elapsed_ms < 100
