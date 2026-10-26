# SPEC-006: Model resolution

Status: draft
Last reviewed: 2026-10-26
Affected paths: src/superharness/engine/model_router.py, src/superharness/engine/model_fallback.py, docs/reference/adapter-models.md

Model resolution turns a harness and a tier into a concrete model id.
`resolve_model_for_tier` in `engine/model_router.py` is the production path;
`resolve_model` is a separate legacy resolver kept for callers of the
model-map API.

Work names a tier, and superharness's own bindings manifest,
`model-bindings.yaml` in its config directory (`SUPERHARNESS_CONFIG_DIR`, else
`$XDG_CONFIG_HOME/superharness`), is the single place a tier becomes a model
id, inside one provider's ladder. superharness reads no other tool's
configuration. Discovery confirms that the bound model is available; it never
chooses a model the bindings did not name.

## Requirements

- [REQ-601] When runtime bindings define a default for a harness, tier resolution returns that binding for `claude-code`, `codex-cli`, `opencode` and `pi`.
- [REQ-602] When runtime bindings are missing and discovery finds no model, resolution falls back to the adapter manifest's auth-compatible chain.
- [REQ-603] Direct resolution prefers the runtime binding over the retired static model map.
- [REQ-604] When a tier is bound, tier resolution returns the bound model even if discovery reports other models, and asks discovery about the bound model first, then the rest of the same provider's ladder.
- [REQ-605] When discovery reports the bound model unavailable, resolution falls back to the next available model of the same provider's ladder (higher tiers first), never to another provider or an unnamed model, and records a `model-binding-unavailable` failure. When no ladder model is confirmed, the binding stands and the failure is still recorded.
- [REQ-607] Bindings are read only from superharness's own config directory, never from another tool's configuration such as `$XDG_CONFIG_HOME/modrouter/`.
- [REQ-606] A discovery cache entry is used only when it names the currently bound model, so an edited binding takes effect on the next resolution.

## Scoped Invariants

- [INV-601] Under ChatGPT authentication, fallback resolution never returns a deprecated static override.

## Known gaps

- superharness has no command yet to refresh its bindings against provider catalogs or to warn when they are stale; until one exists, the operator edits the manifest by hand.
- `resolve_model` still ends on a literal `claude-sonnet-4-6` when every other source is empty. Removing the compatibility resolver is a separate migration.

## Verification & Validation

- REQ-601 -> tests/unit/test_dynamic_resolution.py::test_runtime_bindings_replace_per_harness_fallback
- REQ-602 -> tests/unit/test_dynamic_resolution.py::test_discovery_failure_falls_back_to_auth_compatible_manifest
- REQ-603 -> tests/unit/test_model_router.py::TestResolveModel::test_direct_resolution_prefers_runtime_binding
- REQ-607 -> tests/unit/test_dynamic_resolution.py::test_bindings_are_read_from_superharness_config_never_modrouter
- REQ-604 -> tests/unit/test_dynamic_resolution.py::test_binding_beats_a_discovered_model_outside_the_ladder
- REQ-604 -> tests/unit/test_dynamic_resolution.py::test_available_binding_is_returned_and_probed_first
- REQ-605 -> tests/unit/test_dynamic_resolution.py::test_unavailable_binding_falls_back_inside_its_provider_and_is_journaled
- REQ-605 -> tests/unit/test_dynamic_resolution.py::test_no_available_ladder_model_keeps_binding_and_is_journaled
- REQ-606 -> tests/unit/test_dynamic_resolution.py::test_stale_cache_entry_does_not_override_an_edited_binding
- INV-601 -> tests/unit/test_dynamic_resolution.py::test_chatgpt_fallback_uses_manifest_compatible_model
