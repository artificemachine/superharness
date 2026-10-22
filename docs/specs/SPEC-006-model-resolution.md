# SPEC-006: Model resolution

Status: draft
Last reviewed: 2026-09-24
Affected paths: src/superharness/engine/model_router.py, src/superharness/engine/model_fallback.py, docs/adapter-models.md

Model resolution turns a harness and a tier into a concrete model id.
`resolve_model_for_tier` in `engine/model_router.py` is the production path;
`resolve_model` is a compatibility wrapper kept for callers of the legacy
model-map API.

## Requirements

- [REQ-601] When runtime bindings define a default for a harness, tier resolution returns that binding for `claude-code`, `codex-cli`, `opencode` and `pi`.
- [REQ-602] When runtime bindings are missing and discovery finds no model, resolution falls back to the adapter manifest's auth-compatible chain.
- [REQ-603] Direct resolution prefers the runtime binding over the retired static model map.

## Scoped Invariants

- [INV-601] Under ChatGPT authentication, fallback resolution never returns a deprecated static override.

## Known gaps

- Resolution order is cache, then live discovery, then runtime bindings. Runtime bindings therefore decide only when the cache misses and discovery returns nothing. Whether bindings should outrank discovery is an owner decision.
- `resolve_model` still ends on a literal `claude-sonnet-4-6` when every other source is empty. Removing the compatibility resolver is a separate migration.

## Verification & Validation

- REQ-601 -> tests/unit/test_dynamic_resolution.py::test_runtime_bindings_replace_per_harness_fallback
- REQ-602 -> tests/unit/test_dynamic_resolution.py::test_discovery_failure_falls_back_to_auth_compatible_manifest
- REQ-603 -> tests/unit/test_model_router.py::TestResolveModel::test_direct_resolution_prefers_runtime_binding
- INV-601 -> tests/unit/test_dynamic_resolution.py::test_chatgpt_fallback_uses_manifest_compatible_model
