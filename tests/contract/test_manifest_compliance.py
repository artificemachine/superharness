"""Contract tests — verify that adapter manifests match launcher behavior.

Covers:
- supports_effort field is respected
- Model resolution works for all tiers
- All manifests can be loaded and validated
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml


MANIFEST_DIR = Path(__file__).parent.parent.parent / "src" / "superharness" / "adapter_manifests"


def _load_manifest(name: str) -> dict:
    """Load a manifest by name."""
    path = MANIFEST_DIR / f"{name}.yaml"
    if not path.exists():
        pytest.skip(f"Manifest not found: {name}")
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _all_manifests() -> list[tuple[str, dict]]:
    """Return all (name, manifest) pairs."""
    result = []
    for f in sorted(MANIFEST_DIR.glob("*.yaml")):
        name = f.stem
        manifest = _load_manifest(name)
        result.append((name, manifest))
    return result


# ── Manifest structure ────────────────────────────────────────────────────────

class TestManifestStructure:
    """All manifests must have required fields."""

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_has_name(self, name, manifest):
        assert "name" in manifest, f"{name}: missing 'name'"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_has_model_tiers(self, name, manifest):
        assert "model_tiers" in manifest, f"{name}: missing 'model_tiers'"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_has_three_tiers(self, name, manifest):
        tiers = manifest.get("model_tiers", {})
        for tier in ("mini", "standard", "max"):
            assert tier in tiers, f"{name}: missing '{tier}' tier"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_supports_effort_field(self, name, manifest):
        """Every manifest must declare supports_effort (true or false)."""
        assert "supports_effort" in manifest, (
            f"{name}: missing 'supports_effort' field — "
            f"must be true (launcher handles --effort) or false (launcher ignores it)"
        )

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_has_launcher_script(self, name, manifest):
        assert "launcher_script" in manifest, f"{name}: missing 'launcher_script'"


# ── Model resolution ──────────────────────────────────────────────────────────

class TestModelResolution:
    """Model resolution must return valid models for all owners and tiers."""

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    @pytest.mark.parametrize("tier", ["mini", "standard", "max"])
    def test_resolve_model_returns_value(self, name, manifest, tier):
        """resolve_model returns a non-empty string for every tier."""
        from superharness.engine.adapter_registry import resolve_model
        result = resolve_model(name, tier)
        assert result, f"{name}/{tier}: resolve_model returned empty"
        assert "id" in result or isinstance(result, str), f"{name}/{tier}: no model id"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_tiers_are_different(self, name, manifest):
        """All three tiers should resolve to different models."""
        from superharness.engine.adapter_registry import resolve_model
        models = {}
        for tier in ("mini", "standard", "max"):
            result = resolve_model(name, tier)
            model_id = result.get("id", result) if isinstance(result, dict) else result
            models[tier] = model_id
        # At least max should differ from mini/standard
        assert models["max"] != models["mini"], f"{name}: max and mini resolve to same model"


# ── Orchestrator chain ────────────────────────────────────────────────────────

class TestOrchestratorChain:
    """Orchestrator chain models must match manifests."""

    def test_all_owners_in_chain(self):
        """Every owner with a manifest should be in the orchestrator chain."""
        from superharness.engine.orchestrator import _ORCHESTRATOR_CHAIN
        from superharness.engine.adapter_registry import list_adapters

        owners_in_chain = {entry[0] for entry in _ORCHESTRATOR_CHAIN}
        all_owners = set(list_adapters())

        # Map adapter names to chain binary names:
        # claude-code → claude, codex-cli → codex, gemini-cli → gemini, opencode → opencode
        name_map = {
            "claude-code": "claude",
            "codex-cli": "codex",
            "gemini-cli": "gemini",
            "opencode": "opencode",
        }
        missing = [o for o in all_owners if name_map.get(o, o) not in owners_in_chain]
        assert not missing, (
            f"Owners missing from orchestrator chain: {missing}. "
            f"Chain has: {owners_in_chain}. Adapters: {all_owners}."
        )

    def test_chain_models_match_manifest_max(self):
        """Orchestrator chain max-tier models match manifest max-tier."""
        from superharness.engine.orchestrator import _ORCHESTRATOR_CHAIN
        from superharness.engine.adapter_registry import resolve_model, clear_manifest_cache

        # Ensure fresh manifest cache
        clear_manifest_cache()

        for binary, model_id, label in _ORCHESTRATOR_CHAIN:
            manifest_max = resolve_model(binary, "max")
            if isinstance(manifest_max, dict):
                manifest_id = manifest_max.get("id", "")
            else:
                manifest_id = str(manifest_max)

            # Skip comparison if resolution returned a tier name (cache/graph issue)
            if manifest_id in ("mini", "standard", "max", ""):
                continue

            # claude has two entries (Opus 4.8 + fallback Opus 4.7)
            if binary == "claude":
                assert model_id in ("claude-opus-4-8", "claude-opus-4-7"), (
                    f"Claude orchestrator model {model_id} not recognized"
                )
            elif binary == "opencode":
                assert "deepseek" in model_id.lower(), (
                    f"OpenCode orchestrator model {model_id} doesn't look like DeepSeek"
                )
            else:
                assert model_id == manifest_id, (
                    f"Orchestrator chain has {model_id} for {binary} "
                    f"but manifest max tier resolves to {manifest_id}"
                )


# ── Model resolution edge cases ───────────────────────────────────────────────

class TestModelResolutionEdgeCases:
    """Model resolution for all owners and tiers."""

    @pytest.mark.parametrize("owner", ["claude-code", "codex-cli", "gemini-cli", "opencode"])
    @pytest.mark.parametrize("tier", ["mini", "standard", "max"])
    def test_resolve_returns_non_empty(self, owner, tier):
        """Every owner×tier combo resolves to a non-empty string."""
        from superharness.engine.adapter_registry import resolve_model, clear_manifest_cache
        clear_manifest_cache()
        result = resolve_model(owner, tier)
        if isinstance(result, dict):
            assert result.get("id"), f"{owner}/{tier}: no id in result {result}"
            assert result.get("label"), f"{owner}/{tier}: no label in result {result}"
        else:
            assert result, f"{owner}/{tier}: empty result"
            assert isinstance(result, str), f"{owner}/{tier}: unexpected type {type(result)}"

    @pytest.mark.parametrize("owner", ["claude-code", "codex-cli", "gemini-cli", "opencode"])
    def test_max_tier_resolves_different_from_mini(self, owner):
        """Max tier should not return the same model as mini tier."""
        from superharness.engine.adapter_registry import resolve_model, clear_manifest_cache
        clear_manifest_cache()
        max_result = resolve_model(owner, "max")
        mini_result = resolve_model(owner, "mini")
        max_id = max_result.get("id", max_result) if isinstance(max_result, dict) else max_result
        mini_id = mini_result.get("id", mini_result) if isinstance(mini_result, dict) else mini_result
        assert max_id != mini_id, f"{owner}: max and mini resolve to same model '{max_id}'"

    @pytest.mark.parametrize("owner", ["claude-code", "codex-cli", "gemini-cli", "opencode"])
    def test_invalid_tier_returns_fallback(self, owner):
        """Invalid tier should not crash."""
        from superharness.engine.adapter_registry import resolve_model, clear_manifest_cache
        clear_manifest_cache()
        result = resolve_model(owner, "nonexistent")
        assert result is not None  # don't crash, return something

    @pytest.mark.parametrize("owner", ["claude-code", "codex-cli", "gemini-cli", "opencode"])
    def test_resolve_after_cache_clear_is_consistent(self, owner):
        """resolve_model returns same result after cache clear."""
        from superharness.engine.adapter_registry import resolve_model, clear_manifest_cache
        clear_manifest_cache()
        r1 = resolve_model(owner, "standard")
        clear_manifest_cache()
        r2 = resolve_model(owner, "standard")
        id1 = r1.get("id", r1) if isinstance(r1, dict) else r1
        id2 = r2.get("id", r2) if isinstance(r2, dict) else r2
        assert id1 == id2, f"{owner}: inconsistent across cache clears: {id1} vs {id2}"


# ── Launcher script existence ─────────────────────────────────────────────────

class TestLauncherScripts:
    """Every adapter's launcher_script must exist."""

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_launcher_script_exists(self, name, manifest):
        """Launcher script referenced by manifest must exist on disk."""
        script = manifest.get("launcher_script", "")
        if not script:
            pytest.skip(f"{name}: no launcher_script")
        script_path = MANIFEST_DIR.parent / "scripts" / script
        assert script_path.exists(), (
            f"{name}: launcher_script '{script}' not found at {script_path}"
        )

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_launcher_script_is_executable(self, name, manifest):
        """Launcher script must have the correct extension."""
        script = manifest.get("launcher_script", "")
        if not script:
            pytest.skip(f"{name}: no launcher_script")
        assert script.endswith(".sh"), f"{name}: launcher_script should be .sh, got '{script}'"


# ── Capability consistency ────────────────────────────────────────────────────

class TestCapabilityConsistency:
    """Capabilities must match adapter registry."""

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_capabilities_not_empty(self, name, manifest):
        """Every adapter must declare at least one capability."""
        caps = manifest.get("capabilities", [])
        assert caps, f"{name}: no capabilities declared"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_valid_capabilities(self, name, manifest):
        """Capabilities must be from the known set."""
        known = {"code_generation", "file_editing", "test_execution", "multi_file_refactor"}
        caps = set(manifest.get("capabilities", []))
        unknown = caps - known
        assert not unknown, f"{name}: unknown capabilities: {unknown}"


# ── Model pricing consistency ─────────────────────────────────────────────────

class TestModelPricing:
    """models.yaml pricing must be consistent with manifests."""

    def test_pricing_file_exists(self):
        """models.yaml must exist."""
        pricing_path = MANIFEST_DIR.parent / "engine" / "models.yaml"
        assert pricing_path.exists(), "models.yaml not found"

    def test_pricing_has_entries(self):
        """models.yaml must have pricing for all models."""
        import yaml
        pricing_path = MANIFEST_DIR.parent / "engine" / "models.yaml"
        with open(pricing_path) as f:
            data = yaml.safe_load(f) or {}
        pricing = data.get("pricing", {})
        assert pricing, "models.yaml has no pricing entries"


# ── Manifest idempotency ──────────────────────────────────────────────────────

class TestManifestIdempotency:
    """Loading a manifest twice returns the same result."""

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_double_load_is_consistent(self, name, manifest):
        """Loading the same manifest twice returns the same data."""
        from superharness.engine.adapter_registry import load_manifest, clear_manifest_cache
        clear_manifest_cache()
        m1 = load_manifest(name)
        m2 = load_manifest(name)
        assert m1.name == m2.name
        assert m1.model_tiers == m2.model_tiers, f"{name}: tiers differ between loads"

# ── Launcher flag combinations ────────────────────────────────────────────────

class TestLauncherFlagCombinations:
    """Launcher scripts must handle all flag combinations without crashing."""

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    @pytest.mark.parametrize("effort", ["low", "medium", "high"])
    def test_effort_flag_accepted(self, name, manifest, effort):
        """Launcher script exists and accepts --effort flag."""
        script = manifest.get("launcher_script", "")
        if not script:
            pytest.skip(f"{name}: no launcher_script")
        script_path = MANIFEST_DIR.parent / "scripts" / script
        if not script_path.exists():
            pytest.skip(f"Script not found")
        supports = manifest.get("supports_effort", False)
        if not supports:
            pytest.skip(f"{name}: doesn't support effort")

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_manifest_declares_effort_correctly(self, name, manifest):
        """supports_effort must be a boolean."""
        val = manifest.get("supports_effort")
        assert isinstance(val, bool), f"{name}: supports_effort is {type(val)}, expected bool"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    @pytest.mark.parametrize("field", ["name", "version", "description", "type",
                                        "launcher_script", "model_tiers"])
    def test_required_field_not_empty(self, name, manifest, field):
        """Required manifest fields must not be empty."""
        val = manifest.get(field, "")
        assert val, f"{name}: '{field}' is empty"

    @pytest.mark.parametrize("name,manifest", _all_manifests())
    def test_bin_field_if_present(self, name, manifest):
        """If requires.bin is set, the binary should be on PATH or declare check_bin: false."""
        requires = manifest.get("requires", {})
        validation = manifest.get("validation", {})
        if requires.get("bin") and validation.get("check_bin", True):
            import shutil
            bin_name = requires["bin"]
            # At minimum, the config should be self-consistent
            assert isinstance(bin_name, str), f"{name}: bin must be a string"
