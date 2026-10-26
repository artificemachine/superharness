# SPEC-006: Model resolution

Status: draft
Last reviewed: 2026-10-26
Affected paths: src/superharness/engine/model_router.py, src/superharness/engine/model_fallback.py, src/superharness/engine/model_bindings.py, src/superharness/commands/models.py, docs/reference/adapter-models.md

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
- [REQ-608] `shux models check` reports the bindings file and exits 0 when fresh, 1 when a bound provider is stale (older than `review_after_days`, default 5) or the file is invalid, and 2 when it is missing.
- [REQ-609] `shux models check --probe` reports each binding as available, unavailable or unknown, probing once per harness; one harness's failing probe never hides the others.
- [REQ-610] `shux models init` and `shux models update --apply` never overwrite without a byte-identical backup, refuse invalid input without writing, and leave the original intact when a write fails.
- [REQ-611] `shux models update` proposes only accept-chain models that discovery confirms, never an invented model, and `--apply` keeps every comment of the file.
- [REQ-612] `shux doctor` reports a missing, invalid or stale bindings file without changing its warning count or exit code.
- [REQ-607] Bindings are read only from superharness's own config directory, never from another tool's configuration such as `$XDG_CONFIG_HOME/modrouter/`.
- [REQ-606] A discovery cache entry is used only when it names the currently bound model, so an edited binding takes effect on the next resolution.

## Scoped Invariants

- [INV-601] Under ChatGPT authentication, fallback resolution never returns a deprecated static override.

## Known gaps

- `shux models update` only replaces a dead binding with a model the adapter's accept chain already lists; it does not read provider catalogs, so new models still need a manual edit.
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
- REQ-608 -> tests/unit/test_models_cmd.py::test_check_missing_file_exits_2
- REQ-608 -> tests/unit/test_models_cmd.py::test_check_reports_stale_provider
- REQ-608 -> tests/unit/test_model_bindings.py::test_stale_providers_uses_review_after_days
- REQ-609 -> tests/unit/test_models_cmd.py::test_check_probe_marks_dead_binding
- REQ-609 -> tests/unit/test_models_cmd.py::test_check_probe_survives_one_harness_failure
- REQ-610 -> tests/unit/test_models_cmd.py::test_init_force_keeps_backup
- REQ-610 -> tests/unit/test_models_cmd.py::test_init_from_rejects_invalid_schema_and_writes_nothing
- REQ-610 -> tests/unit/test_models_cmd.py::test_update_apply_failed_replace_leaves_original
- REQ-611 -> tests/unit/test_models_cmd.py::test_update_proposes_nothing_without_confirmed_replacement
- REQ-611 -> tests/unit/test_models_cmd.py::test_update_apply_preserves_comments
- REQ-612 -> tests/unit/test_doctor_model_bindings.py::test_doctor_reports_stale_bindings
- INV-601 -> tests/unit/test_dynamic_resolution.py::test_chatgpt_fallback_uses_manifest_compatible_model
