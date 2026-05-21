# Superharness vs Pi-Mono vs Hermes — Feature Comparison

> Date: 2026-05-07 | Version: superharness v1.51.0

---

## TL;DR

Superharness v1.51.0 has caught up with or surpassed both Pi-Mono and Hermes on most
dimensions relevant to multi-agent orchestration. Two meaningful gaps remain:

1. **Tool-loop guardrails** (from Hermes) — detect and block repeated failing tool calls before they burn budget
2. **Structured compaction in handoffs** (from Pi-Mono) — Goal / Constraints / Progress / Decisions / Next Steps / Files template for richer context continuity

---

## Full Comparison Table

| Capability | Pi-Mono | Hermes | Superharness v1.51.0 |
|---|---|---|---|
| **Task / session state** | Tree with parentId, branching, labels, compaction entries | SQLite sessions + messages | SQLite tasks, handoffs, ledger, decisions, failures |
| **Handoff / context continuity** | `handoff.ts` — focused prompt for fresh session | Auto-compress at 50% context limit with structured summary | `shux handoff generate`, `shux context`, `shux recall` |
| **Event stream** | JSONL RPC / event stream | Gateway streaming consumer (async, token deltas) | `engine/event_stream.py` — DONE |
| **Agent routing** | Single agent runtime | Smart delegation + per-subagent credential routing | `engine/smart_dispatch.py` — skill-match routing — DONE v1.51.0 |
| **Model fallback** | — | Per-subagent model config | `engine/model_fallback.py` — primary → standard → mini — DONE v1.51.0 |
| **Tool-loop guardrails** | — | Repeated fail detection, idempotency check, warn → block | `engine/loop_detector.py` — partial |
| **Approval / risk gate** | Permission-gate extension (path-based) | Smart Approvals — LLM-evaluated risk + session/permanent allowlist | `mcp/approval.py` (risk-classified: low/medium/high) + `guard/state.py` |
| **Credential redaction** | — | — | `guard/redact.py` — DONE |
| **Dangerous command detection** | — | — | `guard/detector.py` — DONE |
| **Skill extraction** | — | Curator: usage tracking, stale marking, archive, dry-run | `engine/skill_extractor.py` + `engine/skill_metrics.py` — DONE |
| **Scheduling / always-on** | — | Session auto-expiry with proactive memory flush | `commands/schedule.py` + quiet-hours — DONE v1.51.0 |
| **MCP / external surface** | RPC mode (`pi --mode rpc`) | ACP adapter (Agent Client Protocol) | `mcp/server.py` — 17 tools, FastMCP HTTP port 7474 — DONE v1.50.0 |
| **Git worktree isolation** | — | Stale pruning (>24h), include files, clean removal | `engine/worktree_ops.py` — basic, missing stale pruning |
| **Terminal UI** | `pi-tui` — differential rendering, overlays, select lists | — | `commands/tui.py` — 5-column Kanban, actions, search — DONE v1.49.0 |
| **Hooks / notifications** | — | `HOOK.yaml` + `handler.py` drop-in per project | `engine/hooks.py` + `mcp/hooks.py` — DONE |
| **Structured compaction** | Goal / Constraints / Progress / Decisions / Next Steps / Files | Goal / Progress / Decisions / Files / Next Steps | Not yet — handoffs use free-form YAML |
| **FTS recall** | — | FTS5 over sessions + messages | `engine/recall.py` — DONE |
| **Usage insights** | — | Model / tool / skill / cost breakdowns from SQLite | Not yet |
| **Session tree / branch history** | Full tree with branch summaries, labels, compaction entries | — | Not yet |
| **Extension / pack model** | Extensions, skills, prompts, themes bundled as packages | Slash command registry | `engine/adapter_registry.py` — manifests only |
| **Discord trigger** | — | — | `modules/actions/discord.py` — DONE v1.51.0 |
| **Multi-agent protocol** | — | Subagent credential routing | `shux delegate`, `engine/adapter_registry.py`, full protocol |

---

## Gap Analysis — What Superharness Still Lacks

### High Priority

| Gap | Source | Effort | Action |
|-----|--------|--------|--------|
| Tool-loop guardrails (repeated fail → warn → block) | Hermes | Low | Extend `engine/loop_detector.py`, wire into watcher |
| Structured compaction in handoffs (Goal/Constraints/Progress/Decisions/Next Steps/Files) | Pi-Mono | Low | Update `engine/handoff_generator.py` template |

### Medium Priority

| Gap | Source | Effort | Action |
|-----|--------|--------|--------|
| `shux insights --days 30` (model/task/skill/cost) | Hermes | Low | New `commands/insights.py` on existing SQLite |
| Proactive session flush before context limit | Hermes | Medium | Trigger `engine/session_flush.py` at size threshold |
| Worktree stale pruning + include files | Hermes | Low | Extend `engine/worktree_ops.py` |
| `shux context --tree` — task tree with branch summaries | Pi-Mono | Medium | Extend `engine/recall.py` + `commands/context.py` |
| Skill curator lifecycle (`shux skills curate --dry-run`) | Hermes | Medium | Extend `engine/skill_metrics.py` |

### Low Priority / Optional

| Gap | Source | Effort | Action |
|-----|--------|--------|--------|
| `shux packs` — bundle adapter manifests, skills, guardrails, prompts | Pi-Mono | High | New `commands/pack.py` + pack spec |
| Shared machine-readable permission/path policy across all adapters | Pi-Mono | Medium | Extend scope-guard → YAML policy |
| ACP adapter (IDE clients without custom integration) | Hermes | High | New `mcp/acp.py` |

---

## What NOT to Pick

| Pattern | Reason |
|---------|--------|
| Pi full agent runtime | Superharness orchestrates agents — it is not one |
| Hermes full gateway runner | Redundant with operator + daemon |
| Telegram/Discord embedded adapters | Use hook system instead |
| Hermes voice pipeline | Out of scope |
| Hermes memory tool (MEMORY.md / USER.md) | Covered by handoffs + ledger |
| Pi TypeScript TUI library | Ported in spirit via curses TUI (v1.49.0) |

---

## Already Shipped from Both Projects

| Pattern | Source | Version |
|---------|--------|---------|
| Event hook system | Hermes | v1.50.0 |
| Risk-classified approval gate | Hermes | v1.50.0 |
| Session flush | Hermes | v1.50.0 |
| Skill extraction + metrics | Hermes | v1.50.0 |
| Smart dispatch routing | Hermes | v1.51.0 |
| Model fallback chain | Hermes | v1.51.0 |
| Schedule quiet hours | Hermes (auto-expiry pattern) | v1.51.0 |
| FTS recall | Hermes | v1.50.0 |
| Credential redaction | Hermes | v1.49.0 |
| Dangerous command detection | Hermes | v1.49.0 |
| JSONL event stream | Pi-Mono | v1.50.0 |
| 5-column terminal Kanban board | Pi-Mono (inspiration) | v1.49.0 |
| MCP / RPC surface (17 tools) | Pi-Mono + Hermes ACP | v1.50.0 |
| Discord trigger adapter | — | v1.51.0 |
