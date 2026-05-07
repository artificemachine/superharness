# Pi-Mono + Hermes Adaptation Audit

> Merged from `AUDIT-pi-mono-superharness-adaptation.md`, `AUDIT-hermes-agent-superharness-adaptation.md`, and `hermes-cherry-pick-audit.md`
> Last updated: 2026-05-07

---

## Guiding Principle

**Don't adopt either project wholesale. Don't dispatch to them as agents.**
Extract self-contained patterns and fold them into superharness as native features.
Pi-mono is TypeScript-first; Hermes is Python but a full agent runtime — neither fits superharness' model of orchestrating other agents via SQLite/YAML/CLI.

---

## Comparison: Pi-Mono vs Hermes vs Superharness (current)

| Capability | Pi-Mono | Hermes | Superharness (v1.51.0) |
|---|---|---|---|
| Session / task state | Tree with parentId, branching, labels | SQLite sessions + messages | SQLite tasks, handoffs, ledger, decisions, failures |
| Handoff / context continuity | `handoff.ts` — focused prompt for fresh session | Context compressor + structured summary | `shux handoff generate`, `shux context`, `shux recall` |
| Event stream | JSONL RPC/event stream | Gateway streaming consumer | `engine/event_stream.py` + `shux events --jsonl` (DONE) |
| Dispatch / agent routing | Single agent runtime | Smart delegation + credential routing | `engine/smart_dispatch.py`, adapter registry, `shux delegate` |
| Model fallback | — | Per-subagent model config | `engine/model_fallback.py` (DONE v1.51.0) |
| Tool-loop guardrails | — | Repeated failure detection, idempotency check | `engine/loop_detector.py` (partial) |
| Approval / gate | Permission-gate extension | Smart Approvals (LLM-evaluated risk) + session/permanent allowlist | `mcp/approval.py` (risk-classified), `guard/state.py` |
| Credential redaction | — | — | `guard/redact.py` (DONE) |
| Dangerous command detection | — | — | `guard/detector.py` (DONE) |
| Skill extraction | — | Skill curator with lifecycle (usage, stale, archive) | `engine/skill_extractor.py` + `engine/skill_metrics.py` (DONE) |
| Scheduling / always-on | — | Session auto-expiry with memory flush | `commands/schedule.py` + quiet hours (DONE v1.51.0) |
| MCP / external tool surface | RPC mode | ACP adapter | `mcp/server.py` — 17 tools, FastMCP HTTP (DONE v1.50.0) |
| Git worktree isolation | — | Stale pruning, include files, clean removal | `engine/worktree_ops.py` (basic, missing stale pruning) |
| Terminal UI | `pi-tui` differential rendering | — | `commands/tui.py` — 5-column Kanban (DONE v1.49.0) |
| Hooks / notifications | — | `HOOK.yaml` + `handler.py` drop-in | `engine/hooks.py` + `mcp/hooks.py` (DONE) |
| Context compaction | Structured compaction (Goal/Constraints/Progress/Decisions/Next Steps) | Auto-trigger at 50% context limit | Not yet |
| FTS recall | — | FTS5 over sessions/messages | `engine/recall.py` (DONE) |
| Usage insights | — | Model/tool/skill/cost breakdowns from SQLite | Not yet |
| Extension/pack model | Extensions, skills, prompts, themes bundled | Slash command registry | `engine/adapter_registry.py` (manifests only) |
| Session tree / branch history | Full tree with branch summaries | — | Not yet |

---

## What Superharness Still Lacks (gap list)

### From Pi-Mono

| Gap | Value | Effort | Next Step |
|-----|-------|--------|-----------|
| `shux context --tree` — session/task tree with branch summaries | Medium | Medium | Extend `engine/recall.py` + `commands/context.py` |
| Structured compaction format in handoffs (Goal/Constraints/Progress/Decisions/Next Steps/Files) | High | Low | Update `engine/handoff_generator.py` template |
| `shux packs` — bundle adapter manifests, skills, guardrails, prompt templates | Medium | High | New `commands/pack.py` + pack spec |
| Shared machine-readable permission/path policy across all adapters | Medium | Medium | Extend `adapters/claude-code/hooks/scope-guard.sh` → YAML policy |

### From Hermes

| Gap | Value | Effort | Next Step |
|-----|-------|--------|-----------|
| Tool-loop guardrails (repeated same fail → warn → block) | **High** | Low | Extend `engine/loop_detector.py`, wire into watcher |
| Skill curator lifecycle (`shux skills curate --dry-run`) | Medium | Medium | Extend `engine/skill_metrics.py` |
| `shux insights --days 30` (model/tool/cost breakdowns) | Medium | Low | New `commands/insights.py` querying existing SQLite |
| Worktree stale pruning + include files | Medium | Low | Extend `engine/worktree_ops.py` |
| Proactive session flush before context limit | High | Medium | Extend `engine/session_flush.py` with size trigger |
| ACP adapter (expose contract/tasks to IDE clients without custom integration) | Low | High | New `mcp/acp.py` |

---

## Already Shipped from Both Audits

| Pattern | Source | Shipped |
|---------|--------|---------|
| Event hook system | Hermes | `engine/hooks.py` + `mcp/hooks.py` (v1.50.0) |
| Approval gate with risk classification | Hermes | `mcp/approval.py` + `guard/state.py` |
| Session flush | Hermes | `engine/session_flush.py` |
| Skill extraction | Hermes | `engine/skill_extractor.py` + `engine/skill_metrics.py` |
| Smart dispatch routing | Hermes | `engine/smart_dispatch.py` (v1.51.0) |
| Model fallback chain | Hermes | `engine/model_fallback.py` (v1.51.0) |
| FTS5 recall | Hermes | `engine/recall.py` |
| Credential redaction | Hermes | `guard/redact.py` |
| Dangerous command detection | Hermes | `guard/detector.py` |
| Schedule quiet hours | Hermes (auto-expiry pattern) | `commands/schedule.py` (v1.51.0) |
| JSONL event stream | Pi-Mono | `engine/event_stream.py` |
| Terminal UI (differential column view) | Pi-Mono (inspiration) | `commands/tui.py` (v1.49.0) |
| MCP / RPC surface | Pi-Mono + Hermes ACP | `mcp/server.py` (v1.50.0) |

---

## Recommended Next Picks (priority order)

1. **Tool-loop guardrails** — extend `engine/loop_detector.py`, wire into watcher dispatch events. Highest reliability impact, low effort.
2. **Structured compaction in handoffs** — update `engine/handoff_generator.py` with Goal/Constraints/Progress/Decisions/Next Steps/Files template.
3. **`shux insights`** — query existing SQLite for model/task/skill cost breakdowns. Low effort, high operator value.
4. **Proactive session flush** — trigger `engine/session_flush.py` at context size threshold, not only on timeout.
5. **Worktree stale pruning** — add to `engine/worktree_ops.py`: skip worktrees older than 24h with no changes.

---

## What NOT to Pick

| Pattern | Reason |
|---------|--------|
| Pi full agent runtime | Superharness orchestrates agents — it is not one |
| Hermes full gateway runner | Redundant with operator + daemon |
| Telegram/Discord embedded adapters | Use hook system instead |
| Hermes voice pipeline | Out of scope |
| Hermes memory tool (MEMORY.md/USER.md) | Covered by handoffs + ledger |
| Pi TypeScript TUI library | Ported in spirit via curses in `commands/tui.py` |
