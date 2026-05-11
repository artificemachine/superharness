# Claude-Mem Adaptation Audit

> Last updated: 2026-05-11
> Companions: [docs/CONCEPT-claude-mem-integration.md](CONCEPT-claude-mem-integration.md), [docs/PLAN-claude-mem-integration.md](PLAN-claude-mem-integration.md)

---

## Guiding Principle

**Don't adopt claude-mem wholesale. Don't run it alongside superharness.**
Extract self-contained patterns and fold them into superharness as native features expressed in the superharness idiom. Claude-mem is a per-agent memory plugin with auto-injection at its core; superharness is multi-agent task coordination with operator gating at its core. The two postures collide where they overlap, so we adopt mechanisms, not defaults.

---

## Comparison: claude-mem vs Superharness (current)

| Capability | claude-mem v13.0.1 | Superharness (this branch) |
|---|---|---|
| Primary problem | One agent forgets between sessions | Many agents step on each other |
| Unit of state | Observation (tool call summary) | Task with FSM lifecycle |
| Cross-session continuity | Auto-injects past observations into next prompt | Hands off via SQLite + handoff records |
| Cross-agent coordination | One IDE at a time per profile | Claude Code + Codex + Gemini + OpenCode share one contract |
| Source of truth | SQLite + Chroma vector store | SQLite only |
| Lifecycle | Implicit (hook events) | Explicit FSM: todo to plan_proposed to plan_approved to in_progress to report_ready to review_* to done |
| Approval model | Automatic, opt-out with `<private>` tags | Operator-gated, agents never self-close |
| Stack | TypeScript, Express 5, BullMQ, ioredis, pg, React 19, Chroma, Claude Agent SDK | Python 3.11+, click, pydantic, fastmcp |
| External egress | Anthropic / Gemini / OpenRouter, Chroma embeddings, optional Telegram/Discord/Slack | None by default |
| OAuth handling | Reads Claude OAuth from keychain, injects into worker subprocess | Doesn't touch OAuth |
| Recall surface | Semantic (Chroma) + mem-search skill | FTS5 over handoffs + ledger |
| Privacy primitive | `<private>...</private>` regex strip at hook layer | Same regex, applied at every write boundary |
| Per-profile isolation | `CLAUDE_MEM_DATA_DIR` + `37700 + (uid % 100)` port derivation | `SUPERHARNESS_DATA_DIR` + `SUPERHARNESS_DASHBOARD_PORT` |
| Citation surface | `/api/observation/{id}` viewer URL | `/api/observation/<id>` route + `shux observation show <id>` CLI |
| Auto-capture cadence | Every hook event (Setup, SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, Stop) | None yet (deferred); will land at `report_ready` only |
| LLM summarizer | Always-on, provider-pluggable | None yet (deferred); will be opt-in with a noop default |

---

## Already Shipped from This Audit (this branch)

| Pattern | Source | Shipped |
|---------|--------|---------|
| Privacy tag stripping at write boundary | claude-mem `<private>` hook strip | `utils/privacy.py` |
| Env-var multi-profile isolation | `CLAUDE_MEM_DATA_DIR` + per-user port | `utils/paths.py` (`SUPERHARNESS_DATA_DIR`, `SUPERHARNESS_DASHBOARD_PORT`) |
| Per-task observation snapshot table | claude-mem observations + Chroma metadata | `engine/observations_dao.py` + schema v13 (`task_observations`) |
| Citation URL pattern | `/api/observation/{id}` viewer | `/api/observation/<id>` dashboard route + `shux observation show <id>` CLI |
| Iteration-by-iteration TDD plan doc style | their CLAUDE.md plan-then-implement discipline | `docs/PLAN-claude-mem-integration.md` |

---

## Recommended Next Picks (priority order)

| Priority | Pattern | Effort | Implementation Site |
|----------|---------|--------|---------------------|
| 1 | Summarizer adapter interface (provider-agnostic: noop, Anthropic, Gemini, OpenRouter) | Medium | `engine/summarizer.py` (new), tested with a noop default |
| 2 | Auto-capture on `report_ready` transition that invokes the summarizer and writes to `task_observations` | Low (once 1 lands) | `engine/lifecycle_rules.py` or transition hook |
| 3 | Sibling citation routes (`/api/handoff/<id>`, `/api/decision/<id>`, `/api/failure/<id>`) using the id-parser already extracted in iteration 4 | Low | `commands/observation.py` parser + new branches in `dashboard-ui.py` |
| 4 | Token-cost annotations on `shux context` and `shux recall` output | Low | tiktoken-style counter, sort by relevance times inverse cost |
| 5 | Lifecycle event sink to existing `claw-relay` (Telegram, Discord) for on-the-go monitoring | Medium | New sink reusing `engine/event_stream.py` |
| 6 | Optional semantic recall via `sqlite-vec` extension + local embeddings (no Chroma, no Python deps) | High | New `engine/semantic_recall.py`, lazy index over existing handoffs |
| 7 | Adapter contracts for Gemini CLI, OpenCode, Cursor (mine their hook surface from `plugin/hooks/hooks.json`) | High | New directories under `adapters/` |

---

## What NOT to Pick

| Pattern | Reason |
|---------|--------|
| Auto-injection of prior observations into the next system prompt | Breaks operator gating. Observations stay retrievable, never auto-applied. |
| Hook-every-event capture cadence | Generates noise. Capture at lifecycle transitions only, where the signal-to-noise ratio is high. |
| Express + React viewer UI on a worker port | Existing dashboard at `:8787` already covers the surface. Not worth the Bun/Node dep gravity. |
| OAuth token injection into a long-running worker subprocess | Tokens stay in the operator's keychain. Subprocesses get short-lived credentials at most. |
| BullMQ + ioredis + Postgres stack | SQLite stays the sole runtime data path. WAL plus busy_timeout is enough for the agent fan-in we see. |
| `curl \| bash` installer | `pipx install superharness` is the canonical path. No remote-fetched shell scripts. |
| "Auto-bump every dependency to latest, including majors, daily" | Inverts the trust model. Major version bumps require integration testing, not a cron. |
| 30-language README translation pipeline | Cosmetic. Not in scope. |
| Chroma MCP for embeddings (external embedding API) | Reintroduces network egress superharness deliberately avoids. Local embedding via Ollama plus `sqlite-vec` is the path if semantic recall is needed. |
| Pro / SaaS pivot patterns (license keys, tunnel provisioning) | Out of scope for an OSS coordination tool. |

---

## What Each Side Wins On

- **claude-mem wins** on: implicit recall ("what did the agent observe last time"), zero-friction install for a single user, breadth of IDE integrations (Claude Code, Gemini CLI, OpenCode, Cursor), viewer UX.
- **Superharness wins** on: operator gating, multi-agent coordination, explicit lifecycle with TDD enforcement, FSM rigor, zero default egress, no OAuth in long-running subprocesses, deterministic test surface.

Adopting from claude-mem is therefore about mechanisms (privacy strip, observation table, citation route, env-driven isolation) rather than defaults (auto-injection, every-hook capture, OAuth-in-worker).
