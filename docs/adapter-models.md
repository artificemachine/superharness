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
| `max` | `claude-opus-4-8` | Opus 4.8 | versioned: `4.8` default, `4.7`/`4.6` pin available |
| `max-1m` | `claude-opus-4-8[1m]` | Opus 4.8 (1M) | auto-promoted when effort=max AND tokens > 200K |

**Rationale:** one model per tier from the current Claude family. The `max` tier
was promoted Opus 4.6 → 4.7 (2026-04-17) → 4.8 (2026-05-28) as each became the
default flagship. The `max-1m` tier activates automatically when a max-effort task
estimates more than 200 K input tokens (`should_use_1m_context()` in taxonomy.py).
Opus 4.8 is priced at $5/$25 per MTok input/output (same as 4.7/4.6).

### Model bump log — claude-code

| Date | Tier | Old model | New model | Reason |
|---|---|---|---|---|
| 2026-04-17 | `max` | `claude-opus-4-6` | `claude-opus-4-7` | Opus 4.7 is the current flagship |
| 2026-04-17 | `max-1m` | (new) | `claude-opus-4-7[1m]` | 1M context tier for large prompts |
| 2026-05-28 | `max` | `claude-opus-4-7` | `claude-opus-4-8` | Opus 4.8 is the current flagship; `4.7` retained as version pin |
| 2026-05-28 | `max-1m` | `claude-opus-4-7[1m]` | `claude-opus-4-8[1m]` | Track 4.8 for large-prompt tier |

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

## pi adapter

Source of truth: `src/superharness/adapter_manifests/pi.yaml`.

| Tier | Provider-qualified model id | Label |
|---|---|---|
| `mini` | `deepseek/deepseek-v4-flash` | DeepSeek V4 Flash |
| `standard` | `deepseek/deepseek-v4-flash` | DeepSeek V4 Flash |
| `max` | `deepseek/deepseek-v4-pro` | DeepSeek V4 Pro |

**Rationale:** Pi's authenticated DeepSeek provider exposes two coding models.
Flash covers the cheap/fast and default workhorse roles; Pro is reserved for the
highest-quality tier. Reusing Flash for two tiers is explicit and preferable to
inventing an unverified third model.

### Activation evidence — 2026-08-26

- Pi CLI version `0.73.1` reproduced twice.
- Safe offline model discovery reproduced and listed both selected IDs.
- Two bounded Flash probes and two bounded Pro probes each exited zero, returned a
  terminal assistant message with `stopReason: stop`, and emitted no tool-execution
  events. Probes used no session, context files, extensions, skills, prompt templates,
  or tools.
- No credential value was read, written, or recorded.

### Pi worker activation evidence — 2026-08-26

- Pi CLI version: `0.73.1`.
- Approved provider/model: `deepseek/deepseek-v4-flash`.
- Run 1: `2026-08-26T16:20:37Z`; sanitized prompt SHA-256
  `133a9685b268198649324434ba06d52f9ab4918a792fac94dce655fbdc84eb93`;
  exit `0`; result `pass`; stopReason `stop`; exact file/scope verified; valid
  terminal stream; cleanup verified.
- Run 2: `2026-08-26T16:23:02Z`; sanitized prompt SHA-256
  `33af538d4aba0db1c662d1600020f6d2d245ca54a822d00e88c6830bf52f4753`;
  exit `0`; result `pass`; stopReason `stop`; exact file/scope verified; valid
  terminal stream; cleanup verified.
- Reviewer decision: APPROVE — two independently approved Pi worker runs reproduced successful exact-scope edits using deepseek/deepseek-v4-flash in distinct disposable worktrees; both exited 0 with stopReason stop, valid terminal streams, and verified cleanup.

### Pi orchestrator activation evidence — 2026-08-26

- Timestamp: `2026-08-26T17:23:23Z`.
- Pi CLI version: `0.73.1`.
- Requested provider/model: `deepseek/deepseek-v4-pro`.
- Actual provider/model: `deepseek/deepseek-v4-pro`.
- Prompt SHA-256: `06fb34316c4435b572bba8fe44220590ba73c0b41b44212a26b3c1cc8bd357f9`.
- Exit: `0`.
- Assistant messages: `1`.
- Agent-end events: `1`.
- Valid bounded stream: `yes`.
- Complete valid decomposition: `yes`.
- Produced-owner set: `{codex-cli, pi}`.
- Tools: `--no-tools`.
- Fresh disposable worktree: `yes`.
- Worktree modifications: `0`.
- Cleanup verified: `yes`.
- Reviewer decision: APPROVE — the separately approved Pi live decomposition at 2026-08-26T17:23:23Z used Pi CLI 0.73.1 with requested and actual deepseek/deepseek-v4-pro, exited 0 with one assistant message and one agent_end in a valid bounded stream, returned a complete valid decomposition with produced-owner set {codex-cli, pi}, ran with --no-tools in a fresh disposable worktree, left zero modifications, and completed verified cleanup; the earlier schema-invalid attempt is excluded from evidence.

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
