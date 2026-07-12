# superharness brain — why 4 agent CLIs, what tiers mean, Ollama + vLLM fleet

Saved from brain-scan follow-up session, 2026-07-12. Companion to `docs/brain-scan-2026-07-12.md`.

## Correction to the 2026-07-12 brain scan

The scan's brains inventory listed 3 agent CLIs — incomplete. **opencode is a 4th brain**:

- `MODEL_MAP` entry at `src/superharness/engine/model_router.py:31-35` (deepseek-chat / deepseek-v4-pro per tier)
- 3rd in the classifier fallback chain: `opencode run -m {model} {prompt}` (model_router.py:208)
- **Primary reasoner in discussion routing, ranked equal to claude** — at max-tier discussions claude and opencode get `max` while gemini/codex are capped at `standard` for cost (`_DISCUSSION_TIER_ROUTING`, model_router.py:650-667)
- `shux doctor` maps opencode tiers to fleet (local) models

## Why multiple agent CLI hosts (claude / codex / gemini / opencode)

1. **Independent quota pools** — when one vendor rate-limits, `is_agent_quota_limited` excludes it and work reroutes to the others. One vendor down ≠ system down.
2. **Cross-agent peer review requires a different brain** — `_PEER_AGENTS` cycles claude→gemini→codex→claude so no agent approves its own plan. Structurally impossible with a single host.
3. **Fallback recovery** — exhausted-retry tasks reroute to a different agent whose CLI binary is actually installed (`_agent_cli_reachable`, shipped v1.77.0).
4. **Independent auth/billing** — each CLI carries its own subscription; cost spread instead of concentrated.

## Tiers — 3 buckets, not a range

`VALID_TIERS = {"mini", "standard", "max"}` (model_router.py:38). Classification produces one tier + one effort; `resolve_model(target, tier)` maps the tier to the agent's actual model (project models.yaml override → adapter registry → MODEL_MAP fallback).

| Tier | Semantics (from `_CLASSIFY_PROMPT`) | claude-code | codex-cli | gemini-cli | opencode |
|---|---|---|---|---|---|
| mini | docs, config, boilerplate, no multi-step reasoning | haiku | gpt-5.1-codex-mini | 2.5-flash | deepseek-chat |
| standard | typical multi-file coding, debugging, tests | sonnet | gpt-5.3-codex | 2.5-pro | deepseek-v4-pro |
| max | architecture, migration, security audit, failed 2+ times | flagship (opus) | gpt-5.4 | 2.5-pro | deepseek-v4-pro |

Why only 3: matches every vendor's real model ladder; keeps the classifier output to one word (a small local model classifies reliably); and granularity comes from the **second orthogonal axis** — `effort` (low/medium/high) — so the routing space is 3×3.

Extra routing layers on top:
- `chatgpt_account_overrides` in models.yaml — swaps API-only codex models when on ChatGPT auth (model_router.py:512-537)
- `_DISCUSSION_TIER_ROUTING` — per-agent tier caps inside multi-agent discussions

## GPU fleet — Ollama AND vLLM both already supported

`_call_fleet` (model_router.py:215-244) speaks plain OpenAI-compatible `/chat/completions` — which is vLLM's native API as well as Ollama's. No code change needed to accept either.

- `fleet.yaml` supports per-tier endpoints: code resolves `endpoints.mini → endpoints.standard → endpoints.all` (same for `models.*`)
- The live `~/.config/superharness/fleet.yaml` already sketches the vLLM lab boxes (per-tier endpoints on the sidecar port) in a commented block — enabling vLLM = uncomment + fill, config-only
- Vault topology: `notes/10_ai/tools/opencode/opencode-fleet-overview.md` (4 GPU VMs, vLLM behind on-demand sidecars, RKE2 HA) — authoritative source is gpu-fleet-dashboard's `FLEET-CONTEXT.md` (`/sync-gpu-fleet`)

**Known live bug (from the brain scan):** fleet config names Ollama model `qwen2.5:7b`, but the running Ollama only has `qwen2.5:0.5b` — every fleet call fails silently, which is what keeps the failure-analysis→pause learning loop dormant (the L5 blocker). Fix = `ollama pull qwen2.5:7b` or point the fleet at a vLLM endpoint.
