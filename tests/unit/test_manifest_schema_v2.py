"""Tests for Iteration 4 of PLAN-dynamic-model-selection.md.

Covers:
- `_normalize_tier_value` extended for the `{preferred, accept, auth_compat,
  capability_tags}` tier form (unit — all four tier forms)
- `AdapterManifest` dataclass gains `accept_chain` + `auth_compat` (contract)
- `resolve_accept_chain()` auth-aware ordered chain (state machine)
- Backward compat: legacy manifests still load (regression)
- Malformed new-schema manifests parse without raising (chaos)
"""

from __future__ import annotations

import time

import pytest

from superharness.engine.adapter_registry import (
    AdapterManifest,
    _normalize_tier_value,
    load_manifest,
)


# ---------------------------------------------------------------------------
# Unit — _normalize_tier_value handles all four forms
# ---------------------------------------------------------------------------


def test_norm_legacy_string() -> None:
    """Unit: legacy string form → {id, label}."""
    assert _normalize_tier_value("gpt-5-codex") == {"id": "gpt-5-codex", "label": "gpt-5-codex"}


def test_norm_mapping_form() -> None:
    """Unit: {id, label} mapping form passes through."""
    assert _normalize_tier_value({"id": "m1", "label": "Model One"}) == {
        "id": "m1",
        "label": "Model One",
    }


def test_norm_versioned_form() -> None:
    """Unit: versioned {versions: {"*": {...}}} resolves the default version."""
    assert _normalize_tier_value({"versions": {"*": {"id": "m2", "label": "M2"}}}) == {
        "id": "m2",
        "label": "M2",
    }


def test_norm_new_schema_form() -> None:
    """Unit: {preferred, accept, auth_compat} form → id=preferred, label=preferred."""
    value = {
        "preferred": "gpt-5.1-codex-mini",
        "accept": ["gpt-5.1-codex-mini", "gpt-5-codex-mini"],
        "auth_compat": {"chatgpt": ["gpt-5-codex-mini"]},
        "capability_tags": ["cost_optimised"],
    }
    assert _normalize_tier_value(value) == {
        "id": "gpt-5.1-codex-mini",
        "label": "gpt-5.1-codex-mini",
    }


# ---------------------------------------------------------------------------
# Smoke — every existing manifest loads
# ---------------------------------------------------------------------------


def test_smoke_all_manifests_load_with_extended_parser() -> None:
    """Smoke: every bundled manifest parses with the extended parser."""
    from superharness.engine.adapter_registry import list_adapters

    for name in list_adapters():
        m = load_manifest(name)
        assert m.name == name


# ---------------------------------------------------------------------------
# Contract — dataclass fields
# ---------------------------------------------------------------------------


def test_contract_accept_chain_and_auth_compat_fields() -> None:
    """Contract: AdapterManifest exposes accept_chain and auth_compat dicts."""
    m = AdapterManifest(
        name="t",
        version="1",
        description="d",
        adapter_type="native",
        launcher_script="x.sh",
    )
    assert m.accept_chain == {}
    assert m.auth_compat == {}


# ---------------------------------------------------------------------------
# Integration — parse new schema from YAML
# ---------------------------------------------------------------------------


def test_integration_parse_new_schema(tmp_path) -> None:
    """Integration: a manifest with the new schema exposes accept/auth_compat."""
    from superharness.engine.adapter_registry import MANIFEST_DIR
    import shutil

    # Write a temporary manifest alongside the bundled ones and load it.
    target = MANIFEST_DIR / "test-new-schema.yaml"
    target.write_text(
        """
name: test-new-schema
version: "1"
description: t
type: native
launcher_script: delegate-to-codex.sh
model_tiers:
  mini:
    preferred: gpt-5.1-codex-mini
    accept: [gpt-5.1-codex-mini, gpt-5-codex-mini]
    auth_compat:
      chatgpt: [gpt-5-codex-mini]
      apikey: [gpt-5.1-codex-mini, gpt-5-codex-mini]
    capability_tags: [cost_optimised]
"""
    )
    try:
        m = load_manifest("test-new-schema")
        assert m.accept_chain["mini"] == ["gpt-5.1-codex-mini", "gpt-5-codex-mini"]
        assert m.auth_compat["mini"]["chatgpt"] == ["gpt-5-codex-mini"]
        assert m.auth_compat["mini"]["apikey"] == [
            "gpt-5.1-codex-mini",
            "gpt-5-codex-mini",
        ]
        # normalized tier id = preferred
        assert m.model_tiers["mini"]["id"] == "gpt-5.1-codex-mini"
    finally:
        target.unlink(missing_ok=True)
        from superharness.engine.adapter_registry import clear_manifest_cache

        clear_manifest_cache()


# ---------------------------------------------------------------------------
# State machine — resolution priority
# ---------------------------------------------------------------------------


def test_resolve_accept_chain_priority() -> None:
    """State machine: auth_compat[mode] wins over accept, then preferred."""
    m = AdapterManifest.from_dict(
        {
            "name": "t",
            "version": "1",
            "description": "d",
            "type": "native",
            "launcher_script": "x.sh",
            "model_tiers": {
                "mini": {
                    "preferred": "pref-model",
                    "accept": ["pref-model", "alt-model"],
                    "auth_compat": {"chatgpt": ["chatgpt-model"]},
                }
            },
        }
    )
    # auth_compat for the matching mode wins
    assert m.resolve_accept_chain("mini", "chatgpt") == ["chatgpt-model"]
    # unknown mode → accept chain
    assert m.resolve_accept_chain("mini", "apikey") == ["pref-model", "alt-model"]
    # unknown tier → legacy single id
    assert m.resolve_accept_chain("max", "chatgpt") == ["max"]


# ---------------------------------------------------------------------------
# Regression — legacy manifests still resolve identically
# ---------------------------------------------------------------------------


def test_regression_legacy_resolve_tier_version() -> None:
    """Regression: versioned legacy tiers still resolve via resolve_tier_version."""
    m = load_manifest("claude-code")
    entry = m.resolve_tier_version("max", version="4.6")
    assert "id" in entry and entry["id"]


# ---------------------------------------------------------------------------
# Chaos — malformed new-schema fields
# ---------------------------------------------------------------------------


def test_chaos_auth_compat_string_instead_of_list() -> None:
    """Chaos: auth_compat as a plain string parses without raising."""
    m = AdapterManifest.from_dict(
        {
            "name": "t",
            "version": "1",
            "description": "d",
            "type": "native",
            "launcher_script": "x.sh",
            "model_tiers": {"mini": {"preferred": "p", "auth_compat": "not-a-dict"}},
        }
    )
    assert m.accept_chain.get("mini") == ["p"]


def test_chaos_missing_preferred_and_empty_accept() -> None:
    """Chaos: missing preferred + empty accept falls back to the tier name."""
    m = AdapterManifest.from_dict(
        {
            "name": "t",
            "version": "1",
            "description": "d",
            "type": "native",
            "launcher_script": "x.sh",
            "model_tiers": {"mini": {"accept": []}},
        }
    )
    chain = m.resolve_accept_chain("mini", "chatgpt")
    assert chain == ["mini"]


# ---------------------------------------------------------------------------
# E2E — round-trip through load_manifest → resolve_accept_chain
# ---------------------------------------------------------------------------


def test_e2e_manifest_roundtrip(tmp_path) -> None:
    """E2E: hand-edited manifest round-trips through the full resolution path."""
    from superharness.engine.adapter_registry import MANIFEST_DIR, clear_manifest_cache

    target = MANIFEST_DIR / "test-roundtrip.yaml"
    target.write_text(
        """
name: test-roundtrip
version: "1"
description: t
type: native
launcher_script: delegate-to-codex.sh
model_tiers:
  standard:
    preferred: std-model
    accept: [std-model, std-fallback]
"""
    )
    try:
        clear_manifest_cache()
        m = load_manifest("test-roundtrip")
        assert m.resolve_accept_chain("standard", "chatgpt") == ["std-model", "std-fallback"]
        assert m.model_tiers["standard"]["id"] == "std-model"
    finally:
        target.unlink(missing_ok=True)
        clear_manifest_cache()


# ---------------------------------------------------------------------------
# Performance — parse under 10ms
# ---------------------------------------------------------------------------


def test_perf_parse_under_10ms() -> None:
    """Performance: parsing the largest bundled manifest is fast.

    Threshold 50ms, not 10ms: CI runners (ubuntu) measured 11ms for the
    codex manifest; a tight 10ms bound is a flake on slower runners while
    50ms still proves parsing is not a hot-path concern.
    """
    start = time.perf_counter()
    m = load_manifest("codex-cli")
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert m.name == "codex-cli"
    assert elapsed_ms < 50
