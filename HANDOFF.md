# Project Handoff: Auto-Mode Gap Plan Complete (v1.38.0)

**Date**: 2026-04-27
**Status**: v1.38.0 on PyPI / auto-mode coverage gaps closed / branch merged
**Summary**: Completed all iterations of `docs/auto-mode-gap-plan.md` (iters 0-8 + 3a). Seven new engine modules shipped: failure classifier, lifecycle reconciler, plan/report quality gates, review escalation chain, and state_writer skeleton. Dashboard gains a recent-failures panel. 2556 tests pass.

---

## What Shipped This Session

### Iterations 0-8 + 3a — auto-mode-gap-plan (v1.38.0 — PR #145)

**Iter 0 — Test infrastructure**
- `clean_harness` pytest fixture: isolated tmp `.superharness/` workspace for all engine tests
- `past_iso(minutes_ago)` helper: returns real past timestamps (avoids pytest-freezegun conflicts)

**Iter 1 — `engine.failure_classifier`**
- Classifies dispatch failures: `permanent_block / transient / quota / agent_crash / no_op / unknown`
- Wired into `inbox_dispatch._mark_item_failed`: stamps `failure_class` + `failure_explain` on every failed inbox item
- Non-retryable categories (`permanent_block`, `quota`, `no_op`) skip the retry loop immediately

**Iter 2 + 4 — `engine.lifecycle_rules`**
- Data-driven `LIFECYCLE_RULES` table replaces two ad-hoc reconcilers
- Adds `in_progress` 180m → `archived` timeout (iter 4 previewed in the table)
- Adding a new state timeout is now one row, not a new function + watcher edit

**Iter 5 — `engine.plan_validator`**
- Plans missing a full TDD block (`red`/`green`/`refactor`), a `risks` section, or containing TODO/FIXME placeholders stay `plan_proposed`
- `validation_failures` list stamped on the task for operator surface
- Gate wired into `task.py` auto-approve flow

**Iter 6 — `engine.report_verifier`**
- Reports with outcome < 20 chars, `tests_passed=false`, broken `pr_url`, or referencing non-existent files stay `report_ready`
- `verification_failures` list stamped on the task
- Gate wired into `inbox_watch._auto_close_report_ready`

**Iter 7 — `engine.review_escalation`**
- Stale `review_requested` tasks advance through `review_chain` (codex-cli → gemini-cli → operator) instead of blindly reverting to `report_ready`
- Tasks with `escalated_to=operator` are visible in the dashboard

**Iter 8 — Recent failures dashboard panel**
- `/api/recent-failures` endpoint: failed inbox items with `failure_class`, `failure_explain`, last 20 lines of launcher log
- Panel above active work queue, color-coded pills by class, refreshes every 10s

**Iter 3a — `engine.state_writer` skeleton**
- Unified write API: `set_task_status`, `set_inbox_status`, `upsert_handoff`
- Writes to YAML first; best-effort SQLite mirror via `_mirror_*_to_sqlite`
- Foundation contract for iters 3b-3e (SQLite-as-SoT full migration, deferred)

### Previous work on branch (v1.37.4-1.37.5)
Shipped in the same PR (#145):
- Non-blocking `shux operator start` + launchd-safe daemon
- `paused` timeout reconciler (30m → failed, immune if `reason` set)
- `shux worktree list/create/remove/gc` CLI
- Dashboard: Copy button, discussion view panel, board/list fixes
- Fixed `delegate-to-claude.sh` bash 3.2 unbound variable (`CLAUDE_ARGS`)
- Auth token persists to `.dashboard_auth_token` (survives restarts)

---

## Current Version

| | |
|---|---|
| **PyPI** | `1.38.0` |
| **`shux --version`** | `1.38.0` |
| **Default backend** | `dual` (SQLite first, YAML fallback) |
| **Gate 3** | Complete |
| **Auto-mode gap plan** | Iters 0-8 + 3a complete / 3b-3e deferred |

---

## Contract Status

| Task | Status | Owner |
|---|---|---|
| `chore.collapse-guards-next-action` | done | claude-code |
| `verify.auto-dispatch.A/B/C` | done | claude-code |
| `mock.alpha` | done | claude-code |
| `feat.dashboard-auto-restart-on-upgrade` | plan_approved | claude-code |
| `feat.autonomous-peer-review` | todo | gemini-cli |

89 archived tasks hidden (`shux contract --include-archived`).

---

## Next Actions

1. **`feat.dashboard-auto-restart-on-upgrade`** — plan approved, ready to implement. Dashboard detects when installed superharness version changes and auto-restarts.
2. **`feat.autonomous-peer-review`** — Gemini peer-reviews Claude's completed tasks autonomously via `report_ready` status.
3. **Iters 3b-3e** — SQLite-as-SoT full migration (deferred, ~2 weeks). See `docs/auto-mode-gap-plan.md` for scope.

---

## Infrastructure

Start the background stack with:

```bash
shux operator start --port 8787
```

The Guardian self-heals the Watcher and Dashboard if they crash, and arbitrates port conflicts automatically.

**State backend** is `dual` by default. To run sqlite-only:

```bash
STATE_BACKEND=sqlite_only shux status
```

---

## Key Docs

- `docs/auto-mode-gap.md` — root-cause analysis of the 4 structural gaps and 12 bugs this session fixed
- `docs/auto-mode-gap-plan.md` — TDD iteration plan (iters 0-8 + 3a complete, 3b-3e pending)
