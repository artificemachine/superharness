# Concept: features worth borrowing from claude-mem

Date: 2026-05-11
Status: proposal, no code yet
Source: review of `thedotmack/claude-mem` v13.0.1 (Apache-2.0)

## Framing

`claude-mem` is a per-agent memory plugin: lifecycle hooks capture tool observations, an LLM compresses them, and the result is auto-injected into the next session's system prompt. `superharness` is multi-agent task coordination with operator-gated lifecycle and SQLite-as-source-of-truth. Different layers, but `claude-mem` has shipped a handful of mechanisms that compose cleanly with the existing `superharness` model.

This doc ranks integration candidates by value-to-cost, gated on what `superharness` already has:

- `operator_memory.py` (failure-pattern recall with confidence)
- `shux recall` (FTS5 over handoffs and ledger)
- `claude-code` and `codex-cli` adapters
- Dashboard at `:8787`
- `shux schedule` (cron-style dispatch)

The constraints below are non-negotiable for any borrowed feature:

1. Operator gates every lifecycle transition. No auto-injection into agent prompts.
2. No long-running subprocess holds OAuth tokens.
3. No new outbound network egress by default.
4. SQLite stays the sole runtime source of truth. New tables, never new YAML files.

## High value, low cost (do these first)

### 1. Observation snapshot at `report_ready` transition

When a task moves to `report_ready`, generate a structured summary of the work done (significant tool calls, files touched, decisions made) and attach it to the handoff. `claude-mem` does this continuously at every hook; `superharness` does it once per task at a meaningful boundary. Keeps gating, no auto-injection.

- Implementation: hook on the status transition in `src/superharness/engine/`, call Claude or Gemini, write to a new `task_observations` table next to `operator_memory`.
- Surface: `shux context <id>` returns the snapshot alongside existing handoff content.
- Scope: ~150 lines plus a prompt template.

### 2. Privacy tag stripping at the handoff write boundary

`claude-mem` strips `<private>...</private>` content at the hook layer before the worker. Apply the same regex at every superharness write path that takes free-text from agents (handoff, decision, failure, plan, report). Single safety floor that does not exist today.

- Implementation: utility in `src/superharness/utils/`, invoked from every commit-to-SQLite write site.
- CLI flag: `--no-privacy-strip` for debugging only.
- Scope: ~30 lines.

### 3. Citations: stable IDs and URL views for prior reasoning

`claude-mem` exposes every observation at `http://localhost:37777/api/observation/{id}`. Handoffs, decisions, and failures already have keys in SQLite. Expose them in the existing dashboard at `/handoff/{id}`, `/decision/{id}`, `/failure/{id}`. Agents can then reference prior reasoning in plans (`see decision/42`) instead of recopying it into every handoff.

- Implementation: route handlers in `src/superharness/scripts/dashboard-ui.py`, plus `shux cite <id>` for terminal lookup.
- Scope: ~80 lines.

### 4. Per-profile data dir via env var

`claude-mem` reads `CLAUDE_MEM_DATA_DIR` and auto-derives port from `37700 + (uid % 100)`. Add `SUPERHARNESS_DATA_DIR` to override `.superharness/` paths and dashboard port. Lets multiple isolated profiles run on one machine (work, scratch, experiments) without `cd`-juggling. Fits the cmux parallel-session workflow.

- Implementation: env var resolver, override the project-path-to-state-db helper and dashboard bind port.
- Scope: ~50 lines plus a doc paragraph.

## Medium value (take when the cycle opens)

### 5. Live event stream to messaging channels

`claude-mem` ships an observation feed to Telegram, Discord, Slack, and others. `superharness` already emits lifecycle events to the dashboard. Add a second sink that streams *lifecycle transitions only* (not tool calls) through the existing `claw-relay` (Telegram-capable). On-the-go monitoring without standing up new integrations.

- Implementation: new event sink that reuses the existing relay path. `shux event-feed enable --channel telegram --to <chat>`.
- Scope: ~120 lines.

### 6. Adapter contracts for Gemini CLI, OpenCode, Cursor

`claude-mem` has already done the work of mapping each IDE's hook surface to a unified contract. Mine `plugin/hooks/hooks.json` and the per-adapter directories for the shape. No need to install `claude-mem` to learn what each CLI exposes.

- Implementation: new directories under `adapters/`, mirroring `claude-code/` and `codex-cli/`.
- Scope: ~200 lines per CLI, gated on actually using them.

### 7. Optional semantic recall next to FTS5

`shux recall --semantic`. FTS5 wins on exact terms; embeddings win when the exact words have drifted ("flaky chroma sync" vs the words used in the original handoff). Use local embeddings (e.g. `nomic-embed-text` via Ollama) and `sqlite-vec` to keep zero egress, zero new Python deps beyond an extension load.

- Implementation: lazy index over existing handoffs, second search path in the recall command.
- Scope: ~300 lines. Defer until a concrete FTS5 miss is named.

### 8. Token-cost annotations on retrieved context

`claude-mem` pitches "progressive disclosure": when prior context is returned, show how many tokens each chunk would cost to inject. Operator decides what to pull. Pairs with the global token-diet posture.

- Implementation: tiktoken-style counter in `shux context <id>` and `shux recall`, sort by relevance times inverse cost.
- Scope: ~60 lines.

## Skip

| Feature | Why skip |
|---------|----------|
| Auto-inject prior context into the next system prompt | Breaks operator gating, which is the thing superharness exists to enforce. |
| Express + React viewer UI on a worker port | Existing dashboard at `:8787` already covers this surface. Not worth the Bun/Node dep gravity. |
| OAuth-in-worker pattern | Token must stay in the operator's keychain. Not in long-running subprocesses. |
| Auto-bump-every-dep-daily policy | The opposite of how a system other agents trust should run. |
| `curl \| bash` installer | `pipx install superharness` is the canonical path. |
| 30-language README translation pipeline | Cosmetic. Not in scope. |

## Recommended sequence

Land items 1, 2, 3, 4 in a single feature branch. They compose: summarized reports + a privacy floor + citable history + clean multi-profile. That covers roughly 80% of `claude-mem`'s actual value, expressed in the superharness idiom.

Hold 5 until push notifications become a felt need. Hold 6 until a different CLI is in active rotation. Hold 7 until FTS5 has a named miss.

## Out of scope for this doc

- No code, no tests, no acceptance criteria yet. Convert to individual `shux task create` entries when the operator is ready to schedule the work.
- No version bump implied. This is documentation only.
