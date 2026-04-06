# superharness — Onboarding Pipeline Plan

> Plan drafted: 2026-04-06 · Baseline: v1.8.0
>
> Three features that form a user acquisition funnel:
> **explain → onboard → budget guard**

---

## Current State (v1.8.0)

Before reading this plan, know what already exists — several items originally scoped here have shipped:

| Capability | Status | Where |
|------------|--------|-------|
| `--model` flag on delegate | **Shipped (v1.6.0)** | `delegate.py` lines 690–769 |
| Model resolution chain (explicit → task → profile → fallback) | **Shipped** | `delegate.py` + `engine/model_router.py` |
| `model_router.py` with `classify_task()`, `resolve_model()` | **Shipped (v1.7.0)** | `engine/model_router.py` (97 lines) |
| Adapter model passing (Claude + Codex) | **Shipped** | `delegate.py` both launch branches |
| `profile.yaml` with `default_model`, `default_effort` | **Shipped** | `engine/profile.py` + `init_project.py` |
| `_detect()` project detection | **Shipped** | `commands/init_project.py` lines 33–47 |
| `_OnboardingGroup` quickstart help | **Shipped** | `cli.py` lines 25–45 |
| `shux benchmark` cost leaderboard | **Shipped (v1.7.0)** | `commands/benchmark.py` + `engine/benchmark.py` |
| Dashboard `/api/costs` endpoint | **Shipped (v1.8.0)** | `scripts/dashboard-ui.py` |
| `adapter_registry.py` with `model_tiers` per adapter | **Shipped (v1.7.1)** | `engine/adapter_registry.py` |

**What remains to build:** `shux explain`, `shux onboard`, budget guard enforcement, `shux config get/set`, `shux benchmark --models`.

---

## Overview

| Feature | Command | Purpose | Effort |
|---------|---------|---------|--------|
| **Explain** | `shux explain` | "Why should I care?" — quintessence in one screen | ~50 LOC, 1 session |
| **Onboard** | `shux onboard` | "How do I start?" — interactive wizard for real projects | ~300 LOC, 1–2 sessions |
| **Budget Guard** | `shux config set model.budget.*` | "Don't overspend" — cost governance for dispatch | ~150 LOC, 1 session |

### The funnel

```
shux explain     →   shux onboard     →   budget guard
  "why?"               "how?"               "smart spending"
  (10 seconds)         (3 minutes)          (ongoing value)
```

---

## Feature 1: `shux explain`

### What

A single-screen, zero-setup pitch that answers "what is superharness and why does it exist?" — printed to the terminal, no interaction required. Runnable before `init`, before install, before anything.

### Why

Today a new user must read the README (240 lines) or run `shux demo` (which requires understanding what a "task" and "handoff" are). There is no sub-10-second way to grok the core idea. Users bounce before they try `init`.

### Output (draft)

```
superharness — multi-agent task coordination

  The problem
    You delegate work to AI agents (Claude Code, Codex CLI, etc.).
    They forget context between sessions. They clash on shared files.
    Work gets lost, duplicated, or silently dropped.

  The fix
    contract.yaml   — single source of truth for all tasks
    handoffs/       — context passed between agents (nothing lost)
    inbox + watcher — tasks queued, dispatched, tracked, closed

  The flow
    task  →  delegate  →  agent works  →  handoff  →  verify  →  close

  5 commands to know
    shux init        Bootstrap this project
    shux delegate    Hand a task to an agent
    shux contract    See all tasks and their status
    shux dashboard   Open the browser dashboard
    shux close       Mark a task done

  Ready?  Run: shux onboard
  Just exploring?  Run: shux demo
```

### Design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Static vs dynamic | Static text | No dependencies, works before `init` |
| Color/box drawing | Optional (detect TTY) | Works in pipes and dumb terminals |
| Length | ≤25 lines | Must fit one terminal screen |
| Aliases | `shux explain`, `shux why`, `shux wtf` | Multiple discovery paths |
| Exit code | Always 0 | Informational only |
| No-args hint | Update `_OnboardingGroup` quickstart to mention `explain` when no `.superharness/` present | Discoverability without reading docs |

### TDD

```
RED:
  test_explain_prints_to_stdout        — output contains "multi-agent"
  test_explain_exits_zero              — return code 0
  test_explain_no_project_required     — works without .superharness/
  test_explain_mentions_onboard        — contains "shux onboard" CTA
  test_explain_fits_one_screen         — output ≤25 lines

GREEN:
  src/superharness/commands/explain.py  — ~50 lines
  Register "explain" command in cli.py
  Register "why" and "wtf" aliases

REFACTOR:
  Extract shared banner/box-drawing if reused by onboard
```

### Files touched

- `src/superharness/commands/explain.py` (new, ~50 lines)
- `src/superharness/cli.py` (register command + aliases)
- `tests/unit/test_explain.py` (new, ~5 tests)

---

## Feature 2: `shux onboard`

### What

An interactive, step-by-step wizard that walks a new user through setting up superharness on their **real project**. Resumable — tracks progress, skips completed steps, picks up where you left off.

### Why

Today the gap between "I installed superharness" and "I'm productive with it" requires reading docs and knowing which commands to run in which order. `demo` shows a sandbox walkthrough but doesn't set up the user's actual project. `init --interactive` handles one step but drops the user after that with no guidance.

### Flow

```
$ shux onboard

  Step 1/7 — Detect
    Scanning project...
    Found: Python project, git repo, 2 contributors
    ✓ Ready to initialize.

  Step 2/7 — Init
    Setting up .superharness/ for this project...
    ? Autonomy level [1=autonomous / 2=supervised / 3=approval-gated]: 2
    ? What are you working on right now? (one sentence): Adding auth middleware
    ? Install background watcher? [Y/n]: y
    ✓ Project initialized.

  Step 3/7 — Git tracking
    ? Will multiple people or agents share this repo? [Y/n]
      Y → .superharness/ will be committed (inner .gitignore keeps runtime files out)
      n → .superharness/ added to .gitignore (solo use, nothing to share)
    ✓ Git tracking configured.

  Step 4/7 — Doctor
    Running health checks...
    ✓ git: ok
    ✓ claude-code: found (v1.0.33)
    ✓ .superharness/: valid
    ✓ All 8 checks passed.

  Step 5/7 — First Task
    Let's create your first task.
    ? Task title: Add JWT auth to /api/users
    ? Acceptance criteria (comma-separated): tokens validated, refresh works, tests pass
    ? Owner [claude-code]: claude-code
    ✓ Task feat.add-jwt-auth created.

  Step 6/7 — Delegate
    ? Enqueue this task for dispatch now? [Y/n]: y
    ✓ Task enqueued. Watcher will dispatch within 30s.
    (Tip: run 'shux dashboard' to watch it in the dashboard)

  Step 7/7 — Summary
    ┌──────────────────────────────────────────┐
    │  You're set up!                          │
    │                                          │
    │  Project:   ./my-project                 │
    │  Tasks:     1 (feat.add-jwt-auth)        │
    │  Watcher:   running                      │
    │  Dashboard: shux dashboard               │
    │                                          │
    │  What's next:                            │
    │    shux contract    — see all tasks      │
    │    shux dashboard   — open dashboard     │
    │    shux delegate    — hand off more work │
    │    shux recall      — search past work   │
    └──────────────────────────────────────────┘

  Onboarding complete.
```

### Design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Real project vs sandbox | Real project | `demo` already covers sandbox; value is in actual setup |
| Resumable | Yes — `.superharness/onboarding.yaml` | User may stop after step 3, come back later |
| Skip completed steps | Auto-detect (`.superharness/` exists → skip init) | Don't re-do work |
| Works without agent CLIs | Yes — step 6 uses `--print-only` fallback | Don't block onboarding on tool install |
| Inline glossary | Brief parentheticals | "A *handoff* is a note one agent writes for the next" |
| `--non-interactive` flag | Yes — use defaults, no prompts | CI/scripting support |
| Can run multiple times | Idempotent — skips completed, re-runs failed | Safe to re-run |
| `.superharness/` git tracking | Ask: solo vs team | Solo → blanket `.gitignore`; team → commit protocol state, inner `.gitignore` excludes runtime. Default: team (commit) |
| Doctor failure | Non-blocking — print warnings, continue to step 5. Only block if `.superharness/` is corrupt (step 2 must have succeeded). | Users shouldn't be stuck because an optional agent CLI is missing |
| Non-git project | Skip step 3 entirely, print note | Git tracking question is irrelevant without git |

### Dependency decision: interactive prompt library

> **Status: OPEN — not decided yet.**

| Option | Tradeoff |
|--------|----------|
| **A) Plain `click.prompt()` + `click.confirm()`** | Zero new deps (Click is already required). Less polished. Ship fast, polish later. **Recommended for v1.** |
| **B) questionary + rich** | Beautiful arrow-key menus, spinners, styled panels. ~1.1 MB added deps. Conflicts with "zero infrastructure" selling point. Better for v2 polish pass. |
| **C) rich only (no questionary)** | Styled output but still uses Click for prompts. Middle ground. |

For v1: use plain Click. For a later polish pass, evaluate adding questionary/rich if users request better UX. The `_OnboardingGroup` quickstart and `explain` both work fine with plain text today.

### State file

```yaml
# .superharness/onboarding.yaml
version: 1
started: 2026-04-06T10:00:00Z
steps:
  detect:    completed   # 2026-04-06T10:00:01Z
  init:      completed   # 2026-04-06T10:00:15Z
  git_track: completed   # 2026-04-06T10:00:16Z
  doctor:    completed   # 2026-04-06T10:00:18Z
  task:      completed   # 2026-04-06T10:01:02Z
  delegate:  skipped     # user chose not to enqueue
  summary:   completed   # 2026-04-06T10:01:05Z
git_tracking:
  mode: team             # or "solo"
  gitignore_modified: true
```

### TDD

```
RED:
  test_onboard_creates_state_file          — onboarding.yaml exists after run
  test_onboard_skips_init_if_exists        — .superharness/ present → step 2 skipped
  test_onboard_resumes_from_last_step      — partial state → picks up where left off
  test_onboard_step_detect_shows_stack     — output contains detected stack
  test_onboard_step_task_creates_entry     — contract.yaml has the new task
  test_onboard_step_delegate_enqueues      — inbox.yaml has the task
  test_onboard_git_track_solo_adds_gitignore — solo → .superharness/ added to .gitignore
  test_onboard_git_track_team_keeps_commit   — team → .superharness/ NOT in .gitignore
  test_onboard_git_track_inner_gitignore     — inner .gitignore always present (runtime files excluded)
  test_onboard_git_track_idempotent          — re-running doesn't duplicate .gitignore entry
  test_onboard_non_interactive_no_prompts    — --non-interactive uses defaults (team mode)
  test_onboard_idempotent                    — running twice doesn't duplicate
  test_onboard_summary_shows_next_steps      — output contains "shux contract"
  test_onboard_works_without_agent_cli       — no claude/codex → step 6 uses print-only
  test_onboard_fails_gracefully_without_git  — non-git project → step 3 skipped with note
  test_onboard_doctor_failure_non_blocking   — doctor warnings don't block step 5

GREEN:
  src/superharness/commands/onboard.py     — ~300 lines
  Register "onboard" command in cli.py
  State tracking in .superharness/onboarding.yaml

REFACTOR:
  Extract step runner pattern if reusable
  Share detection logic with init --detect (already exists)
```

### Files touched

- `src/superharness/commands/onboard.py` (new, ~350 lines)
- `src/superharness/cli.py` (register command)
- `tests/unit/test_onboard.py` (new, ~16 tests)

### Git tracking step — detailed behavior

**Step 3/7 asks:** "Will multiple people or agents share this repo?"

| Answer | Action | What gets committed |
|--------|--------|---------------------|
| **Yes (team)** | Keep `.superharness/` tracked. Ensure inner `.gitignore` excludes runtime files. | `contract.yaml`, `decisions.yaml`, `failures.yaml`, `handoffs/` |
| **No (solo)** | Append `.superharness/` to root `.gitignore`. State stays on disk (handoffs, recall still work locally — just not committed). | Nothing — all state is local |

**Inner `.gitignore` (always created by `init`)** excludes:

```
# Runtime state — never commit
ledger.md
launcher-logs/
*.flock
*.heartbeat
heartbeat.yaml
watcher.heartbeat
dashboard-health.log
session-progress.md
session-summary-*.md
watcher.yaml
inbox.yaml
modules/
contracts/
review-lenses/
daemon.pid.json

# Secrets — never commit
watcher-env.yaml
.env
*.key
*.pem
```

**Edge cases:**
- If `.gitignore` already has `.superharness/` → skip, don't duplicate
- If user switches from solo to team later → `shux onboard --reconfigure` removes the `.gitignore` entry
- Non-git projects → skip this step entirely, print note
- `--non-interactive` defaults to **team** (commit protocol state)

---

## Feature 3: Budget Guard

> **Note:** Model selection, routing, and adapter integration are already shipped (v1.6.0–v1.8.0).
> This feature covers only the remaining delta: cost governance and the `config` CLI.

### What

Budget enforcement for dispatch — warn or block when daily/weekly spend exceeds a threshold. Plus a `shux config` command for managing project settings, and a `shux benchmark --models` view for model-level cost breakdown.

### Why

Model selection and routing work, but there's no guardrail against overspending. A user who delegates 10 tasks to Opus has no warning until the bill arrives. The benchmark leaderboard shows per-task costs but not per-model aggregates.

### What already exists

```
✓  --model flag on delegate
✓  Model resolution: explicit → task field → classifier → profile default → fallback
✓  model_router.py: classify_task(), resolve_model(), resolve_tier()
✓  profile.yaml: default_model, default_effort, primary_agent
✓  Adapter registry with model_tiers per adapter
✓  benchmark.jsonl recording cost per dispatch
✓  Dashboard /api/costs endpoint
```

### What needs building

| Component | LOC est. | Description |
|-----------|----------|-------------|
| `engine/model_budget.py` | ~80 | `check_budget()` → warn/block based on daily/weekly limits from profile |
| `commands/config.py` | ~60 | `shux config get/set` for profile.yaml keys (model.budget.daily_limit, etc.) |
| `benchmark.py` extension | ~30 | `--models` flag → aggregate by model, show token/cost breakdown |
| `delegate.py` integration | ~15 | Call `check_budget()` before dispatch, respect `--force` override |

### Budget config (stored in profile.yaml)

```yaml
# .superharness/profile.yaml (existing file, new section)
default_model: claude-sonnet-4-6
default_effort: medium
budget:
  daily_limit: 5.00      # USD — warn at 80%, block at 100%
  weekly_limit: 35.00     # USD — optional
  strict: false           # true = hard block; false = warn only (default)
```

### CLI interface

```bash
# Set budget guard
shux config set budget.daily_limit 5.00
shux config set budget.strict true

# View current config
shux config get budget
shux config get default_model

# View model-level cost breakdown
shux benchmark --models

# Override budget block for one dispatch
shux delegate feat.auth-redesign --force
```

### Budget guard behavior

```
Task dispatched with model: claude-opus-4-6
Budget used today: $4.20 / $5.00

→ WARN: Daily budget 84% used. Proceed? [Y/n]

# If over budget (strict mode):
→ BLOCKED: Daily budget exceeded ($5.12 / $5.00).
  Override with --force, or switch to a cheaper model.
  Suggested: --model claude-sonnet-4-6 (estimated $0.45 vs $2.30)
```

### `shux benchmark --models` output

```
Model Usage (last 7 days)
─────────────────────────────────────────
Model              Tasks   Tokens    Cost
claude-opus-4-6        2   116K    $3.28
claude-sonnet-4-6      8   340K    $6.12
claude-haiku-4-5      12    89K    $0.13
─────────────────────────────────────────
Total                 22   545K    $9.53
Budget: $35.00/week — 27% used
```

### Design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where to store budget config | `profile.yaml` (existing) | Don't introduce a new config file — profile already has model settings |
| Token counting | Parse agent CLI output (best-effort) | No API key required; agents already print token counts |
| Cost estimation | Hardcoded price table, overridable | Prices change rarely; user can override |
| Budget enforcement | Warn by default, block with `strict: true` | Don't surprise users with hard blocks |
| `--force` override | Always available, even in strict mode | Operator always has escape hatch |

### TDD

```
RED:
  # Budget
  test_budget_warn_at_threshold             — 80%+ used → warning printed
  test_budget_block_when_exceeded_strict    — strict mode, over limit → exit 1
  test_budget_warn_only_when_not_strict     — non-strict, over limit → warning, continues
  test_budget_override_with_force           — --force bypasses block

  # Config
  test_config_set_writes_profile            — shux config set budget.daily_limit 5.00 → profile.yaml updated
  test_config_get_reads_profile             — shux config get budget.daily_limit → prints "5.00"
  test_config_get_missing_key               — nonexistent key → helpful error

  # Benchmark --models
  test_benchmark_models_shows_usage         — shux benchmark --models → table with model column
  test_benchmark_models_empty               — no records → "no data" message

GREEN:
  src/superharness/engine/model_budget.py   — new (~80 lines)
  src/superharness/commands/config.py       — new (~60 lines)
  src/superharness/commands/benchmark.py    — extend with --models flag (~30 lines)
  src/superharness/commands/delegate.py     — integrate check_budget() (~15 lines)

REFACTOR:
  Consolidate price table with /model-router skill if warranted
```

### Files touched

- `src/superharness/engine/model_budget.py` (new, ~80 lines)
- `src/superharness/commands/config.py` (new, ~60 lines)
- `src/superharness/commands/benchmark.py` (extend, +30 lines)
- `src/superharness/commands/delegate.py` (add budget check, +15 lines)
- `src/superharness/cli.py` (register config command)
- `tests/unit/test_model_budget.py` (new, ~4 tests)
- `tests/unit/test_config_cmd.py` (new, ~3 tests)
- `tests/unit/test_benchmark_models.py` (new, ~2 tests)

---

## Build Order

```
Phase 1: shux explain          ← quick win, ship first
         (1 session, ~50 LOC)

Phase 2: shux onboard          ← depends on explain (CTA at end)
         (1–2 sessions, ~300 LOC)

Phase 3: budget guard          ← independent, can parallelize with phase 2
         (1 session, ~150 LOC)
```

### Dependencies

```
explain  ──→  onboard (explain's CTA points to onboard)
                │
                ├──→  budget guard (onboard could set budget defaults)
                │
explain  ──→  budget guard (explain could mention smart routing)
```

No hard blockers — all three can be built incrementally. `explain` is the obvious first ship.

---

## Inspirations & UX Research

### Top Inspirations

| Tool | GitHub | Pattern to steal | Stars |
|------|--------|-----------------|-------|
| **docker init** | [docker/cli](https://github.com/docker/cli) | Detect → confirm → scaffold. `"Detected: Python. Is this right?"` Pre-filled defaults in brackets. Summary of created files. | Docker CLI |
| **create-astro** | [withastro/astro](https://github.com/withastro/astro) | Houston mascot personality, `--yes` accept-all-defaults, `--dry-run` preview, `--skip-houston` for power users. | 51k |
| **create-next-app** | [vercel/next.js](https://github.com/vercel/next.js) | `"Would you like to use X? (recommended)"` pattern. Saved preferences — `--yes` reuses last answers. | 133k |
| **Charm huh** | [charmbracelet/huh](https://github.com/charmbracelet/huh) | Grouped form fields, 5 built-in themes, dynamic forms that adapt based on previous answers, accessible mode. | 6.7k |
| **Charm wizard-tutorial** | [charmbracelet/wizard-tutorial](https://github.com/charmbracelet/wizard-tutorial) | Step-by-step wizard walkthrough in Bubble Tea + Lip Gloss. 11 commits = 11 milestones. | — |
| **Copier** | [copier-org/copier](https://github.com/copier-org/copier) | YAML-driven questionnaires, answer recording for re-runs, non-destructive updates (won't overwrite user-modified files). | 3.3k |
| **CrewAI** | [crewAIInc/crewAI](https://github.com/crewAIInc/crewAI) | Closest domain match — AI agent framework. Provider/model selection wizard. YAML-driven agent/task config. | 48k |
| **Nx** | [nrwl/nx](https://github.com/nrwl/nx) | AI-detection: auto non-interactive when run by AI agent. A/B testing different onboarding flows. Adaptive prompts based on prior answers. | 25k |
| **Pulumi** | [pulumi/pulumi](https://github.com/pulumi/pulumi) | Running with no args = helpful hints (not error). Template browser with descriptions. Progressive disclosure. | 23k |
| **Fly.io** | [superfly/flyctl](https://github.com/superfly/flyctl) | Hybrid CLI + web: CLI detects and scaffolds, then opens browser for fine-tuning. Self-contained scriptable output. | 2.3k |

### UX Patterns to Apply (ranked by impact)

#### Must-have (high impact, low effort)

| # | Pattern | Source | How to apply in shux |
|---|---------|--------|---------------------|
| 1 | **Detect → confirm** | docker init | `"Detected: Python project, git repo. [Enter to confirm]"` — `_detect()` already does the hard part |
| 2 | **Step counter** | All | `"Step 2/7 — Init"` with styled headers |
| 3 | **`--yes` flag** | create-astro, create-next-app | Accept all defaults, zero interaction. Map to `--non-interactive` |
| 4 | **Gerund → past tense** | Evil Martians | `"Detecting stack..." → "✓ Detected: Python"` |
| 5 | **"Recommended" labels** | create-next-app | `"Enable watcher? (recommended on macOS) [Y/n]"` |
| 6 | **Summary at end** | docker init, create-astro | Table of created files + next commands |
| 7 | **AI-detection** | Nx | Auto non-interactive when `NON_INTERACTIVE=1` or agent env vars detected (`CLAUDE_CODE=1`, `CODEX_CLI=1`) |

#### Should-have (for v2 polish pass, after adding rich/questionary)

| # | Pattern | Source | How to apply in shux |
|---|---------|--------|---------------------|
| 8 | **Arrow-key select menus** | questionary, Charm huh | Replace numbered input with `questionary.select()` for autonomy level, owner, etc. |
| 9 | **Spinners during work** | Rich | `rich.status.Status("Detecting stack...")` while `_detect()` runs |
| 10 | **Saved preferences** | create-next-app, Copier | `profile.yaml` already stores answers — pre-populate on re-run |
| 11 | **Conditional questions** | questionary `when=`, Nx | Only ask about watcher on macOS, only ask about Docker if detected |
| 12 | **Styled banner** | create-astro (Houston) | Rich panel header: `superharness onboard` with version and tagline |

#### Nice-to-have (higher effort)

| # | Pattern | Source | How to apply in shux |
|---|---------|--------|---------------------|
| 13 | **`--dry-run` for wizard** | create-astro | Preview all steps without executing. Already exists for `init` — extend to `onboard` |
| 14 | **Resume on error** | Copier | If step 4/7 fails, next run picks up at step 4. State file tracks this |
| 15 | **YAML-driven wizard steps** | Copier | Define questions externally so modules can extend the wizard |
| 16 | **No-args = helpful hints** | Pulumi | `shux` with no args detects state: no `.superharness/` → suggest `onboard`; has tasks → suggest `contract` |
| 17 | **Hybrid CLI + web** | Fly.io | After `shux onboard`, print `"Open dashboard: shux dashboard"` — CLI scaffolds, web fine-tunes |

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| Time from install to first task dispatched | ~15 min (read docs) | ~3 min (`onboard`) |
| "What is this?" answer | Read README | `shux explain` (10 sec) |
| Model cost visibility | Per-task only (`benchmark`) | Per-model + budget gauge (`benchmark --models`) |
| New user drop-off point | After `init` (no guidance) | After `onboard` step 6 (fully set up) |
| Budget overspend | Silent (no guard) | Warned at 80%, optionally blocked at 100% |
