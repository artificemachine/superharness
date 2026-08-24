# CONCEPT: Content-Addressed Context Hashing + Typed Handoff Boundaries

Source: [[agent_frameworks_considered_harmful_dottxt]] (Rémi Louf, .txt/dottxt — "Agent Frameworks Considered Harmful", AI Engineer World's Fair 2026). Vault note: `notes/10_ai/intel/youtube_intel/agent_frameworks_considered_harmful_dottxt.md`.

Two concrete, buildable ideas from his 2-week personal agent runtime. Not philosophy — both were forced by a real failure he hit in production.

## 1. Content-addressed prompt/context hashing

**What he built:** every prompt component gets hashed and stored separately (git/nix/Makefile-style): system prompt, each skill description, each tool descriptor, the user message. The rendered prompt sent to the model is just an ordered list of hashes, not a raw string.

**What it buys him, for free:**
- **Diffing between runs** — "what changed between these two attempts" becomes a diff over hashes, not eyeballing a wall of text. Shows exactly which component changed (a different skill? a different tool? just the message?).
- **Exact replay** — rebuild the identical request from the graph, resend to a different model, compare output. He used this to migrate off third-party APIs onto open-source/local models with low risk.
- **Real auditability** — chat UIs lie about what the model actually saw (compaction, hidden thinking traces). The hash graph is ground truth.

**Where this applies here:** `shux delegate <id>` builds a context payload for the dispatched subagent (system prompt + task instructions + relevant handoff/decision history). Today `shux diff <id>` (if it does prompt-level diffing at all) is presumably diffing rendered text. Hash each context component going into a dispatch instead, so a retry/re-dispatch can show *which specific ingredient* changed — did the task instructions change, did a referenced skill file change, did prior handoff context change — rather than a flat text diff.

**Concrete next step:** spike a `context_component` table (component_type, sha256, content, first_seen) alongside `task_usage`; wire `shux delegate` to hash-and-store each component before rendering the final prompt; extend `shux diff` to read component hashes when available and fall back to text diff otherwise.

## 2. Typed boundaries as a hard gate, not a soft convention

**The failure that forced it:** with a non-.txt model, ~20% of his emitted events were malformed and got rejected by his own system — silent corruption risk between agents. His fix: two boundaries treated as absolutely non-negotiable —
- **Typed tool calls** at the agent → external-world boundary
- **Typed events** at the agent → agent boundary

**His framing:** "the job of the kernel is to make bad actions impossible, not just unlikely." Schema validation isn't a nice-to-have on the handoff path, it's the thing standing between one agent's garbage output and the next agent silently ingesting it.

**Where this applies here:** audit whether every subtask handoff and event write into `.superharness/state.db` is schema-validated end to end, or whether any path still accepts free-text/loosely-typed payloads that could corrupt downstream task state without erroring loudly. Same applies to OpenClaw agent-to-agent handoffs if any exist outside the markdown/event-log pattern already in place.

**Concrete next step:** enumerate every write path into the events/handoff tables (`shux handoff-write`, `shux task status`, dispatch result ingestion, any MCP tool that writes state) and confirm each one is schema-validated at the boundary, not just at the CLI's happy path. Flag any bypass.

## Explicitly not new here

Event bus over cron, markdown-as-agent-definition, kernel/userland split — all already the shape of superharness (SQLite source-of-truth, YAML export-only, `shux` as the only write path). This talk is external validation of that split, not a new pattern to adopt.

---
Backlog entries: `notes/00_meta/backlog/backlog_index.md` → `## Superharness` section, 2026-08-23.
