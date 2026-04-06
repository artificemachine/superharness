# Handoff for Claude — Paperclip Gap Analysis and Backlog (2026-04-05)

**From:** codex-cli  
**To:** claude-code  
**Project:** `/Users/airm2max/DevOpsSec/superharness`

---

## What Was Completed

- Verified the superharness vs Paperclip comparison against primary repo sources instead of relying on the draft summary alone.
- Wrote a focused gap-analysis doc to [docs/AUDIT-paperclip-gap-analysis.md](/Users/airm2max/DevOpsSec/superharness/docs/AUDIT-paperclip-gap-analysis.md).
- Materialized the roadmap into real contract backlog items in [.superharness/contract.yaml](/Users/airm2max/DevOpsSec/superharness/.superharness/contract.yaml).

No product code was changed in this turn. This was a docs + contract planning pass only.

---

## Key Conclusions

### Do not turn superharness into Paperclip

The comparison still points to different product identities:

- **Paperclip** is a company-level control plane for many agents.
- **superharness** is strongest as a file-native, verification-first, git-friendly handoff protocol for developer workflows.

### What superharness should copy

- Adapter registry formalization
- Runtime-agnostic heartbeat/status contract
- Better operator UX in the existing monitor
- More formal module/plugin SDK shape
- Portable export/import for project state

### What superharness should not copy

- PostgreSQL-centered state
- Heavy “AI company” metaphor as the main UX
- Telemetry-on-by-default posture
- Full React rewrite of the monitor before proving the need

---

## Backlog Added to Contract

The following tasks were added near the end of `.superharness/contract.yaml`:

| Task ID | Owner | Blocked By | Purpose |
|---------|-------|------------|---------|
| `feat.adapter-registry-v1` | `claude-code` | `none` | Manifest-driven adapter routing |
| `feat.heartbeat-contract-v1` | `claude-code` | `feat.adapter-registry-v1` | Runtime-agnostic heartbeat/status schema |
| `feat.monitor-operator-upgrade` | `codex-cli` | `feat.heartbeat-contract-v1` | Stronger operator UX in `:8787` |
| `feat.module-sdk-v1` | `claude-code` | `feat.adapter-registry-v1` | Formalize module SDK/hooks/manifests |
| `feat.project-pack-export-import` | `claude-code` | `feat.module-sdk-v1` | Portable import/export of `.superharness` state |
| `feat.parallel-checkout-safety` | `claude-code` | `feat.project-pack-export-import` | Safe atomic parallel task checkout |

Each task includes:

- `workflow`
- `development_method`
- `test_types`
- explicit `tdd.red / tdd.green / tdd.refactor`
- acceptance criteria

This means they are ready for normal `shux` flow instead of requiring translation from prose later.

---

## Recommended Next Move

### Start with `feat.adapter-registry-v1`

Reason:

- It is the best leverage point.
- It unlocks heartbeat generalization and better future runtime support.
- It reduces hardcoded target branching that currently exists across dispatch paths.

Suggested implementation shape:

1. Add RED tests for manifest loading, capability detection, registry lookup, and generic dispatch routing.
2. Introduce a small adapter manifest/registry layer, likely in `src/superharness/engine/`.
3. Migrate Claude Code and Codex CLI dispatch through that shared interface without breaking current behavior.
4. Add a small `shux adapters list|info|test` surface after the core path works.

Likely touch points:

- `src/superharness/commands/delegate.py`
- `src/superharness/commands/inbox_dispatch.py`
- `src/superharness/engine/`
- `adapters/`
- new unit/integration tests for registry and routing

---

## Files Changed This Turn

- [docs/AUDIT-paperclip-gap-analysis.md](/Users/airm2max/DevOpsSec/superharness/docs/AUDIT-paperclip-gap-analysis.md)
- [.superharness/contract.yaml](/Users/airm2max/DevOpsSec/superharness/.superharness/contract.yaml)
- [paperclip-gap-analysis-to-claude-2026-04-05.md](/Users/airm2max/DevOpsSec/superharness/.superharness/handoffs/paperclip-gap-analysis-to-claude-2026-04-05.md)

---

## Worktree Notes

Current worktree also contains unrelated or pre-existing changes:

- `src/superharness.egg-info/PKG-INFO`
- `src/superharness.egg-info/SOURCES.txt`

There are also untracked instruction files for the new backlog tasks:

- `.superharness/handoffs/feat.adapter-registry-v1-instructions.md`
- `.superharness/handoffs/feat.heartbeat-contract-v1-instructions.md`
- `.superharness/handoffs/feat.module-sdk-v1-instructions.md`
- `.superharness/handoffs/feat.monitor-operator-upgrade-instructions.md`
- `.superharness/handoffs/feat.parallel-checkout-safety-instructions.md`
- `.superharness/handoffs/feat.project-pack-export-import-instructions.md`

I did not edit or clean up those files in this turn.

---

## Verification

No tests were run in this turn.

Reason:

- Only docs and contract state were updated.
- Repo instructions require approval before running test/build commands.

