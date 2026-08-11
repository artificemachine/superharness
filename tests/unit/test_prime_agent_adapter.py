"""Iteration 6 of PLAN-prime-agent-adoptions.md — prime-agent adapter
manifest.

Binding per plan section 7, Resolution 1: this manifest ships INERT. It
must never claim dispatch readiness. Every model id and launch-arg choice
here is UNVERIFIED — prime-agent's real non-interactive flags were never
probed against an installed binary, and none was installed for this work
(a hard stop, not a shortcut — see PLAN section 7).
"""

from __future__ import annotations

from pathlib import Path

import yaml


MANIFEST_PATH = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "superharness"
    / "adapter_manifests"
    / "prime-agent.yaml"
)


def _raw_manifest() -> dict:
    with MANIFEST_PATH.open() as f:
        return yaml.safe_load(f)


def test_manifest_loads_and_passes_compliance():
    """Loads through the same loader tests/contract/test_manifest_compliance.py
    uses (adapter_registry.load_manifest) and validates structurally."""
    from superharness.engine.adapter_registry import clear_manifest_cache, load_manifest

    clear_manifest_cache()
    manifest = load_manifest("prime-agent")

    assert manifest.name == "prime-agent"
    assert manifest.launcher_script == "delegate-to-prime-agent.sh"
    assert set(manifest.model_tiers) >= {"mini", "standard", "max"}
    assert manifest.capabilities  # non-empty


def test_manifest_is_schema_v2():
    """Every tier carries the schema-v2 keys: preferred, accept, auth_compat,
    capability_tags — mirroring codex-cli.yaml's structure."""
    raw = _raw_manifest()
    tiers = raw["model_tiers"]
    assert set(tiers) >= {"mini", "standard", "max"}
    for tier_name, tier in tiers.items():
        for key in ("preferred", "accept", "auth_compat", "capability_tags"):
            assert key in tier, f"tier {tier_name!r} missing schema-v2 key {key!r}"


def test_absent_binary_resolves_gracefully(tmp_path, monkeypatch):
    """With the binary absent (no prime-agent harness is registered — same
    as any uninstalled agent), resolving a model for prime-agent must not
    raise; it falls through to the manifest's preferred model.

    conftest.py stubs claude/codex/gemini/opencode binaries to exit 127
    under SUPERHARNESS_TEST_OFFLINE=1; prime-agent has no such stub because
    it has no registered harness at all (superharness.harnesses.get_harness
    raises KeyError for it), which is the actual "graceful absence" path —
    _discover_for_agent catches that KeyError and returns [], so resolution
    falls through to the manifest without ever touching a binary.
    """
    from superharness.engine.model_router import resolve_model_for_tier

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    for tier in ("mini", "standard", "max"):
        model = resolve_model_for_tier("prime-agent", tier, str(project_dir))
        assert model, f"resolve_model_for_tier returned empty for tier {tier!r}"
        assert isinstance(model, str)


def test_experimental_flag_excludes_from_default_dispatch():
    """The manifest carries the experimental marker on every tier, and the
    orchestrator's live escalation chain (the default automatic-dispatch
    roster) does not include prime-agent."""
    raw = _raw_manifest()
    tiers = raw["model_tiers"]
    assert tiers, "manifest has no model_tiers"
    for tier_name, tier in tiers.items():
        assert "experimental" in (tier.get("capability_tags") or []), (
            f"tier {tier_name!r} is not tagged experimental"
        )

    from superharness.engine.orchestrator import _ORCHESTRATOR_CHAIN

    chain_binaries = {entry[0] for entry in _ORCHESTRATOR_CHAIN}
    assert "prime-agent" not in chain_binaries
