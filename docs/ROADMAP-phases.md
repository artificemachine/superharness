# superharness — Master Phase Roadmap

> Single source of truth for all planned development phases.
> Source docs are listed per phase; this file takes precedence on priority ordering.

**Last updated:** 2026-05-07
**Current version:** v1.51.0

---

## Phase Status Overview

| # | Phase | Status | Iterations | Tests | Est. Hours | Source Doc |
|---|-------|--------|-----------|-------|-----------|------------|
| ✅ | Agent Toolkit Absorption | DONE (2026-05-05) | 6 | ~40 | — | `PLAN-absorb-agent-toolkit-features.md` |
| ✅ 1 | TUI (terminal board) | DONE (2026-05-07, v1.49.0) | 6 | 28 | ~8 | `DECISION-shux-tui-before-pi-hermes-adapters.md` |
| ✅ 2 | MCP Server | DONE (2026-05-07, v1.50.0) | 10 | 56 | ~14 | `PLAN-mcp-server.md` |
| ✅ 3 | Always-On-Agent Merge | DONE (2026-05-07, v1.51.0) | 7 | 29 | ~10 | `ROADMAP.md` |
| ✅ 4 | Hermes Integration (C2) | DONE (2026-05-07, v1.51.0) | partial | 11 | — | `hermes-integration-tdd-plan.md` |
| 5 | Pi / OpenCode Adapters | Optional | TBD | TBD | TBD | `DECISION-shux-tui-before-pi-hermes-adapters.md` |
| ✅ 6 | Windows CI Full Fix | DONE (2026-05-07, v1.51.0) | partial | 18 | — | `windows-native-full-fix-tdd-plan.md` |

---

## Sequencing Rationale

```
TUI (1) → MCP Server (2) → Always-On-Agent (3) → Hermes (4)
                                                          ↓
                                              Pi/OpenCode Adapters (5) [optional, unblocked after TUI]
Windows CI (6) runs in parallel — not blocked by any phase
```

- **TUI before Pi/OpenCode adapters**: operators need visibility before adding new dispatch targets
- **MCP before Always-On-Agent**: MCP tools are the surface through which always-on scheduling is configured
- **Always-On-Agent before Hermes**: Hermes safety net (checkpoint/rollback) is most valuable when the agent runs unattended on a schedule
- **Windows CI**: pure infra/platform work — no feature dependencies, can be picked up any time

---

## Phase 1 — TUI (Terminal Board)

**Status:** DONE — v1.49.0 (2026-05-07)
**Source:** `docs/DECISION-shux-tui-before-pi-hermes-adapters.md`

**Goal:** Read-only terminal dashboard first, then add controlled actions (approve, reject, pause).

**Rationale:** Before adding more dispatch targets (Pi, OpenCode) or automation (Hermes, always-on), operators need a fast way to see task state, agent health, and discussion threads without opening a browser.

### Planned Iterations

| # | Scope |
|---|-------|
| 1 | Read-only board: task list, status, owner columns — curses or Rich layout |
| 2 | Discussion thread view inline |
| 3 | Agent health panel (watcher, daemon, last heartbeat) |
| 4 | Approve / reject / pause actions with confirmation prompt |
| 5 | Keyboard shortcuts and search/filter |
| 6 | Config (refresh interval, color theme, layout) |

**TDD approach:** Each iteration: write failing test (output fixture or Rich renderable assertion) → minimal impl → refactor.

---

## Phase 2 — MCP Server

**Status:** DONE — v1.50.0 (2026-05-07)
**Source:** `docs/PLAN-mcp-server.md`
**Iterations:** 10 | **Tests:** 34 | **Est:** ~14 hours

**Goal:** Expose superharness contract, discussions, and handoffs as MCP tools so Claude Code (and other MCP clients) can read and write protocol state directly via tool calls instead of shelling out to `shux`.

### Planned Iterations

| # | Tools Added | Tests |
|---|-------------|-------|
| 1 | `list_tasks`, `get_task` | 4 |
| 2 | `create_task`, `update_task_status` | 4 |
| 3 | `list_discussions`, `get_discussion` | 3 |
| 4 | `post_discussion_reply` | 3 |
| 5 | `list_handoffs`, `get_handoff` | 3 |
| 6 | `write_handoff` | 3 |
| 7 | `get_ledger`, `append_ledger` | 3 |
| 8 | `run_hygiene` (read-only health check) | 3 |
| 9 | `get_contract_summary` (aggregate) | 4 |
| 10 | Auth, rate-limit, transport config | 4 |

**Total:** 17 tools, 34 tests

**TDD approach:** Each iteration: write tool-call fixture test (request JSON → response schema) → implement handler → refactor.

---

## Phase 3 — Always-On-Agent Merge

**Status:** DONE — v1.51.0 (2026-05-07)
**Source:** `docs/ROADMAP.md`
**Iterations:** 7 | **Tests:** 29 | **Est:** ~10 hours

**Goal:** Merge the standalone `always-on-agent` scheduler into superharness core so recurring task dispatch (cron, Telegram triggers, Discord triggers) is part of the standard install.

### Planned Iterations

| # | Scope | Tests |
|---|-------|-------|
| 1 | Cron expression parser + next-fire calculator | 4 |
| 2 | Telegram trigger adapter | 4 |
| 3 | Discord trigger adapter | 4 |
| 4 | Daemon mode: background loop + pid file + signal handling | 4 |
| 5 | Model fallback chain (primary → fallback on timeout) | 4 |
| 6 | Heartbeat exclude windows (quiet hours, calendar blackouts) | 4 |
| 7 | Config validation + `shux schedule` CLI surface | 3 |

---

## Phase 4 — Hermes Integration

**Status:** PARTIAL — sub-phases A, B, C1, C2, D1, D2 done; full 47-test count pending remaining sub-phase iterations (v1.51.0, 2026-05-07)
**Source:** `docs/hermes-integration-tdd-plan.md`
**Iterations:** 8 (across 4 sub-phases) | **Tests:** 47 planned, ~30 shipped | **Est:** ~19 hours

**Goal:** Integrate Hermes safety layer — dangerous command detection, credential redaction, checkpoint/rollback, smart dispatch routing, event hook system, and proactive session flush.

### Sub-phases and Iterations

#### Sub-phase A — Security Guard
| # | Scope | Tests |
|---|-------|-------|
| A1 | Dangerous command detection (rm -rf, DROP TABLE, etc.) | 6 |
| A2 | Credential redaction in logs and handoffs | 6 |

#### Sub-phase B — Safety Net
| # | Scope | Tests |
|---|-------|-------|
| B1 | Checkpoint / rollback (git stash + restore on failure) | 6 |
| B2 | Smart approval state (re-use recent approvals, don't re-prompt) | 6 |

#### Sub-phase C — Intelligence
| # | Scope | Tests |
|---|-------|-------|
| C1 | Skill extraction from handoffs (auto-populate skill library) | 6 |
| C2 | Smart dispatch routing (choose agent by skill match) | 5 |

#### Sub-phase D — Reliability
| # | Scope | Tests |
|---|-------|-------|
| D1 | Event hook system (pre/post dispatch, pre/post task, on failure) | 6 |
| D2 | Proactive session flush (auto-write handoff before context limit) | 6 |

---

## Phase 5 — Pi / OpenCode Adapters (Optional)

**Status:** Optional — unblocked after Phase 1 (TUI)
**Source:** `docs/DECISION-shux-tui-before-pi-hermes-adapters.md`

**Goal:** Add adapter manifests + launcher scripts for Pi (Raspberry Pi local agent) and additional OpenCode model targets.

**Dependency:** TUI must be stable so operator can monitor new dispatch targets.

**Note:** OpenCode adapter is partially complete (dispatch script exists). Pi adapter requires SSH dispatch path design.

---

## Phase 6 — Windows CI Full Fix

**Status:** PARTIAL — path normalization, runtime pinning, sync excludes shipped (v1.51.0, 2026-05-07); full E2E matrix on Windows still failing (pre-existing)
**Source:** `docs/windows-native-full-fix-tdd-plan.md`
**Iterations:** 8 | **Tests shipped:** 18 | **Est:** ~12 hours

**Goal:** Make the full test matrix pass on Windows: unit, integration, and E2E. Currently all Windows CI jobs fail (pre-existing, confirmed on PR #192).

### Planned Iterations

| # | Scope |
|---|-------|
| 0 | Scope baseline: enumerate all Windows failures, categorize by root cause |
| 1 | Platform runtime abstraction (`platform_runtime.py` — replace `subprocess` direct calls) |
| 2 | Watcher Python-native (replace bash watcher with cross-platform Python loop) |
| 3 | Dispatcher launch path (normalize path separators, shell detection) |
| 4 | Service installation per OS (launchd on macOS, Task Scheduler / NSSM on Windows) |
| 5 | Python runtime pinning (CI matrix: 3.11, 3.12, 3.13 on Windows) |
| 6 | Docs / UX / guardrails (Windows-specific install guide, error messages) |
| 7 | E2E matrix validation (full pass on ubuntu, macos, windows) |

---

## Already Done — Agent Toolkit Absorption

**Completed:** 2026-05-05
**Source:** `docs/PLAN-absorb-agent-toolkit-features.md`
**Iterations completed:** 6

| Iteration | Feature | Status |
|-----------|---------|--------|
| 1 | Tool-loop guardrails (max-retries, backoff) | DONE |
| 2 | `shux handoff generate` (structured handoff from diff) | DONE |
| 3 | FTS-backed `shux recall` (full-text search) | DONE |
| 4 | JSONL event stream (structured audit log) | DONE |
| 5 | Adapter policy gates (per-agent capability constraints) | DONE |
| 6 | Skill curation + usage insights | DONE |
