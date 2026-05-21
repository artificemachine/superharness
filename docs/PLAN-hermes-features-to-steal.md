# Hermes + Pi-Mono Features — Adaptation Plan for Superharness

**Audit date:** 2026-05-07 (baseline), reviewed 2026-05-20
**References:** hermes-agent (Nous Research), pi-mono
**Guiding principle:** Extract self-contained patterns. Don't adopt either project wholesale. Don't dispatch to them as agents.

---

## Already Shipped (13 features from both sources)

| # | Feature | Source | Module(s) | Version |
|---|---------|--------|-----------|---------|
| 1 | Event hook system | Hermes | `engine/hooks.py` + `mcp/hooks.py` | v1.50.0 |
| 2 | Approval gate with risk classification | Hermes | `mcp/approval.py` + `guard/state.py` | — |
| 3 | Session flush | Hermes | `engine/session_flush.py` | — |
| 4 | Skill extraction + metrics | Hermes | `engine/skill_extractor.py` + `engine/skill_metrics.py` | — |
| 5 | Smart dispatch routing | Hermes | `engine/smart_dispatch.py` | v1.51.0 |
| 6 | Model fallback chain | Hermes | `engine/model_fallback.py` | v1.51.0 |
| 7 | FTS5 recall | Hermes | `engine/recall.py` | — |
| 8 | Credential redaction | Hermes | `guard/redact.py` | — |
| 9 | Dangerous command detection | Hermes | `guard/detector.py` | — |
| 10 | Schedule quiet hours | Hermes (auto-expiry) | `commands/schedule.py` | v1.51.0 |
| 11 | JSONL event stream | Pi-Mono | `engine/event_stream.py` | — |
| 12 | Terminal UI (Kanban) | Pi-Mono (inspiration) | `commands/tui.py` | v1.49.0 |
| 13 | MCP tool surface (17 tools) | Pi-Mono + Hermes ACP | `mcp/server.py` | v1.50.0 |

## Intentionally Rejected

| Pattern | Reason |
|---------|--------|
| Hermes single-agent runtime | Superharness orchestrates multiple agents — not one process loop |
| Hermes full gateway runner | Redundant with operator + daemon |
| Telegram/Discord embedded adapters | Use hook system instead |
| Hermes voice pipeline | Out of scope |
| Hermes memory tool (MEMORY.md) | Covered by handoffs + ledger |
| Pi TypeScript TUI library | Ported in spirit via curses in `commands/tui.py` |

---

## Remaining Gaps — Implementation Plan

### From Hermes (6 gaps)

| # | Gap | Value | Effort | Module to extend |
|---|-----|-------|--------|------------------|
| H1 | **Tool-loop guardrails** — repeated same failure → warn → block | **High** | Low | `engine/loop_detector.py`, wire into watcher |
| H2 | Skill curator lifecycle — `shux skills curate --dry-run` | Medium | Medium | `engine/skill_metrics.py` |
| H3 | `shux insights --days 30` — model/tool/cost breakdowns | Medium | Low | New `commands/insights.py` + existing SQLite |
| H4 | Worktree stale pruning + include files | Medium | Low | `engine/worktree_ops.py` |
| H5 | Proactive session flush before context limit | High | Medium | `engine/session_flush.py` + size trigger |
| H6 | ACP adapter — expose contract/tasks to IDE clients | Low | High | New `mcp/acp.py` |

### From Pi-Mono (4 gaps)

| # | Gap | Value | Effort | Module to extend |
|---|-----|-------|--------|------------------|
| P1 | `shux context --tree` — session/task tree with branch summaries | Medium | Medium | `engine/recall.py` + `commands/context.py` |
| P2 | Structured compaction in handoffs (Goal/Constraints/Progress/Decisions/Next Steps/Files) | High | Low | `engine/handoff_generator.py` |
| P3 | `shux packs` — bundle adapter manifests, skills, guardrails, prompt templates | Medium | High | New `commands/pack.py` + pack spec |
| P4 | Shared permission/path policy across all adapters | Medium | Medium | Extend scope-guard → YAML policy |

---

## Priority Execution Plan

### Phase 1: High Value, Low Effort (next sprint)

| Pick | Gap | What | Tests to add | ETA |
|------|-----|------|-------------|-----|
| 1 | H1 | Tool-loop guardrails: detect repeated same-failure patterns in watcher dispatch, auto-escalate to `blocked` after N consecutive fails | `test_loop_detector_escalation.py` | 2h |
| 2 | P2 | Structured handoff compaction: add Goal/Constraints/Progress/Decisions/Next Steps/Files template to `handoff_generator.py` | `test_handoff_compaction_format.py` | 1h |
| 3 | H3 | `shux insights`: query SQLite for per-task model usage, token counts, cost breakdowns, success rates | `test_insights_queries.py` | 2h |

### Phase 2: Medium Value, Medium Effort

| Pick | Gap | What | Tests |
|------|-----|------|-------|
| 4 | H5 | Proactive session flush: trigger `session_flush.py` at 50% context threshold, not just timeout | `test_flush_size_trigger.py` |
| 5 | H2 | Skill curator lifecycle: prune stale skills (>30d unused), promote high-reuse patterns | `test_skill_curation.py` |
| 6 | H4 | Worktree stale pruning: skip/remove worktrees >24h with no changes | `test_worktree_stale_pruning.py` |
| 7 | P1 | `shux context --tree`: render task tree with branch summaries | `test_context_tree.py` |
| 8 | P4 | Machine-readable permission policy: YAML-based adapter policy file | `test_permission_policy.py` |

### Phase 3: Medium-High Effort (when needed)

| Pick | Gap | What |
|------|-----|------|
| 9 | P3 | `shux packs`: bundle manifests + skills + guardrails into distributable units |
| 10 | H6 | ACP adapter: expose contract/tasks to IDE clients (low value, high effort — defer unless demand) |

---

## Verification Strategy

Every gap follows the RED → GREEN → REFACTOR cycle:
1. **RED:** Write a failing test that asserts the gap is present (e.g., `test_guardrails_detect_repeated_failure` fails because repeated failures aren't blocked)
2. **GREEN:** Implement the feature as an additive wrapper (never replace existing behavior)
3. **REFACTOR:** Ensure the new module is independently testable, properly logged, and follows the `except Exception` policy (all exceptions must log)

## Key Docs

| Doc | Purpose |
|-----|---------|
| `AUDIT-pi-hermes-adaptation.md` | Full adaptation audit (source of truth) |
| `hermes-integration-tdd-plan.md` | 8-feature TDD plan (Phases 1-4) |
| `gateway-security.md` | Messaging gateway security comparison |
| `ATTRIBUTIONS.md` | Prior art credits |
| `IMPLEMENTATION-status.md` | Feature tracking with source attribution |
