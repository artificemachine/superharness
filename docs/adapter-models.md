# Adapter model tiers

This document records the model-to-tier mappings superharness ships in
`src/superharness/adapter_manifests/*.yaml`, plus the rationale and sources
behind each choice. Update this file whenever you bump a model in an adapter
manifest.

## Tier semantics

All adapters expose three tiers. Semantics match the global model-selection
rules in `~/.claude/MODEL_SELECTION.md`:

| Tier | Role | When to pick |
|---|---|---|
| `mini` | cheap + fast batch | repeated/templated tasks, short outputs, simple reasoning — errors are cheap to retry |
| `standard` | default workhorse | everything else: implementation, debugging, reviews, long-context |
| `max` | highest quality | hardest tasks only — cross-domain judgment, high-stakes output, deep synthesis |

## claude-code adapter

Source of truth: `src/superharness/adapter_manifests/claude-code.yaml`.

| Tier | Model id (default `*`) | Label | Notes |
|---|---|---|---|
| `mini` | `claude-haiku-4-5-20251001` | Haiku 4.5 | |
| `standard` | `claude-sonnet-4-6` | Sonnet 4.6 | versioned: `4.6` pin available |
| `max` | `claude-opus-4-7` | Opus 4.7 | versioned: `4.7` default, `4.6` pin available |
| `max-1m` | `claude-opus-4-7[1m]` | Opus 4.7 (1M) | auto-promoted when effort=max AND tokens > 200K |

**Rationale:** one model per tier from the current Claude family. The `max` tier
was promoted from Opus 4.6 → Opus 4.7 (2026-04-17) as 4.7 became the default
flagship. The `max-1m` tier activates automatically when a max-effort task
estimates more than 200 K input tokens (`should_use_1m_context()` in taxonomy.py).

### Model bump log — claude-code

| Date | Tier | Old model | New model | Reason |
|---|---|---|---|---|
| 2026-04-17 | `max` | `claude-opus-4-6` | `claude-opus-4-7` | Opus 4.7 is the current flagship |
| 2026-04-17 | `max-1m` | (new) | `claude-opus-4-7[1m]` | 1M context tier for large prompts |

## codex-cli adapter

Source of truth: `src/superharness/adapter_manifests/codex-cli.yaml`.

| Tier | Model id | Label |
|---|---|---|
| `mini` | `gpt-5.1-codex-mini` | GPT-5.1 Codex mini |
| `standard` | `gpt-5.3-codex` | GPT-5.3 Codex |
| `max` | `gpt-5.4` | GPT-5.4 |

### Quality-first codex ranking (2026-04-16)

For coding work, the codex-cli models rank in this order, quality first:

1. `gpt-5.4` — latest frontier agentic coding model (current Codex default)
2. `gpt-5.3-codex` — frontier codex-optimized agentic coding model
3. `gpt-5.2-codex` — frontier agentic coding model
4. `gpt-5.1-codex-max` — codex-optimized flagship for deep and fast reasoning

### Why the chosen mapping

- **mini = `gpt-5.1-codex-mini`** — the picker's only explicit "cheaper, faster,
  but less capable" codex-optimized tier. Best fit for Haiku-role batch work.
- **standard = `gpt-5.3-codex`** — codex-optimized frontier model. Being
  codex-tuned beats the generalist `gpt-5.4` for the daily coding workhorse.
- **max = `gpt-5.4`** — the #1 quality pick. Reserve for hardest reasoning.

Alternatives considered but not chosen:

- `gpt-5.2-codex` as `standard` — superseded by `gpt-5.3-codex` for coding.
- `gpt-5.1-codex-max` as `max` — still valid; replace `gpt-5.4` here if you
  want the whole tier stack codex-optimized at the cost of frontier reasoning.

### Sources

- `gpt-5.2-codex` release: https://openai.com/index/introducing-gpt-5-2-codex/
- `gpt-5.2-codex` model page: https://developers.openai.com/api/docs/models/gpt-5.2-codex
- `gpt-5.1-codex-max` system card: https://openai.com/index/gpt-5-1-codex-max-system-card/
- `gpt-5.1-codex-max` model page: https://platform.openai.com/docs/models/gpt-5.1-codex-max

## How the mapping is consumed

Every task and subtask in `shux adapter-payload --json` (schema v1.2+) carries:

```json
{
  "model_tier":     "standard",
  "resolved_model": { "id": "claude-sonnet-4-6", "label": "Sonnet 4.6" }
}
```

The resolver (`superharness.engine.adapter_registry.resolve_model(owner, tier)`)
walks the adapter manifest for `owner` and looks up `tier` in `model_tiers`.
Unknown owner or tier falls back to `{id: tier, label: tier}` so the payload
stays well-formed even during one-off dispatches.

See `docs/adapter-payload-spec.md` (Resolved model section) for the on-wire
contract.

## How to bump a model

1. Edit the adapter manifest under `src/superharness/adapter_manifests/`.
2. Update **both** `id` and `label` in the relevant tier.
3. Append a dated row under the relevant adapter section here explaining the
   choice.
4. Do **not** bump `schema_version` in `adapter_payload.py` — model bumps are
   content changes, not schema changes. Schema is only bumped when fields
   are added/removed.
