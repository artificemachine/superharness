# superharness — Onboarding Pipeline Plan

> Three features that form a user acquisition funnel:
> **explain → onboard → model-binding**

---

## Overview

| Feature | Command | Purpose | Effort |
|---------|---------|---------|--------|
| **Explain** | `shux explain` | "Why should I care?" — quintessence in one screen | ~50 LOC, 1 session |
| **Onboard** | `shux onboard` | "How do I start?" — interactive wizard for real projects | ~300 LOC, 1–2 sessions |
| **Model Binding** | `shux delegate --model X` | "Make it smart" — cost-aware, right-sized dispatch | ~400 LOC, 3–4 sessions |

### The funnel

```
shux explain     →   shux onboard     →   model binding
  "why?"               "how?"               "smart"
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

### TDD

```
RED:
  test_explain_prints_to_stdout        — output contains "multi-agent"
  test_explain_exits_zero              — return code 0
  test_explain_no_project_required     — works without .superharness/
  test_explain_mentions_onboard        — contains "shux onboard" CTA

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
- `tests/test_explain.py` (new, ~4 tests)

---

## Feature 2: `shux onboard`

### What

An interactive, step-by-step wizard that walks a new user through setting up superharness on their **real project**. Resumable — tracks progress, skips completed steps, picks up where you left off.

### Why

Today the gap between "I installed superharness" and "I'm productive with it" requires reading docs and knowing which commands to run in which order. `demo` shows a sandbox walkthrough but doesn't set up the user's actual project. `init --interactive` handles one step but drops the user after that with no guidance.

### Flow

```
$ shux onboard

  Step 1/6 — Detect
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
    │    shux status      — full dashboard     │
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
| Works without agent CLIs | Yes — step 5 uses `--print-only` fallback | Don't block onboarding on tool install |
| Inline glossary | Brief parentheticals | "A *handoff* is a note one agent writes for the next" |
| `--non-interactive` flag | Yes — use defaults, no prompts | CI/scripting support |
| Can run multiple times | Idempotent — skips completed, re-runs failed | Safe to re-run |
| `.superharness/` git tracking | Ask: solo vs team | Solo → blanket `.gitignore`; team → commit protocol state, inner `.gitignore` excludes runtime. Default: team (commit) |

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

GREEN:
  src/superharness/commands/onboard.py     — ~300 lines
  Register "onboard" command in cli.py
  State tracking in .superharness/onboarding.yaml

REFACTOR:
  Extract step runner pattern if reusable
  Share detection logic with init --detect
```

### Files touched

- `src/superharness/commands/onboard.py` (new, ~350 lines)
- `src/superharness/cli.py` (register command)
- `tests/test_onboard.py` (new, ~14 tests)

### Git tracking step — detailed behavior

**Step 3/7 asks:** "Will multiple people or agents share this repo?"

| Answer | Action | What gets committed |
|--------|--------|---------------------|
| **Yes (team)** | Keep `.superharness/` tracked. Ensure inner `.gitignore` excludes runtime files. | `contract.yaml`, `decisions.yaml`, `failures.yaml`, `handoffs/` |
| **No (solo)** | Append `.superharness/` to root `.gitignore`. | Nothing — all state is local |

**Inner `.gitignore` (always created by `init`)** excludes:

```
# Runtime state — never commit
ledger.md
launcher-logs/
*.flock
*.heartbeat
heartbeat.yaml
watcher.heartbeat
monitor-health.log
session-progress.md
session-summary-*.md
watcher.yaml
inbox.yaml
modules/
contracts/
review-lenses/

# Secrets — never commit
watcher-env.yaml
.env
*.key
*.pem
```

**Edge cases:**
- If `.gitignore` already has `.superharness/` → skip, don't duplicate
- If user switches from solo to team later → `shux onboard --reconfigure` removes the `.gitignore` entry
- Non-git projects → skip this step entirely
- `--non-interactive` defaults to **team** (commit protocol state)

---

## Feature 3: Model Binding

### What

Let superharness bind a specific inference model to a task, agent, or project — so dispatch uses the right model for the job, with cost tracking and budget guards.

### Why

Today superharness dispatches to "claude-code" or "codex-cli" generically. The operator's MODEL_SELECTION.md rules are advisory only — nothing enforces them. A simple `chore.update-deps` task runs on the same model as a complex `feat.auth-redesign`. This wastes budget and ignores the operator's own cost/quality preferences.

### Three levels of binding

```
Project default    →   Task override    →   Auto-router
(lowest priority)      (explicit)           (smart fallback)
```

#### Level 1: Project default

```yaml
# .superharness/config.yaml (or profile.yaml)
model:
  default: claude-sonnet-4-6
  budget:
    daily_limit: 5.00      # USD
    warn_at: 3.50
```

#### Level 2: Task override

```yaml
# contract.yaml — per-task binding
tasks:
  - id: feat.auth-redesign
    owner: claude-code
    model: claude-opus-4-6          # explicit: architecture work
    model_reason: "cross-domain security + perf tradeoffs"

  - id: chore.update-deps
    owner: claude-code
    model: claude-haiku-4-5         # explicit: simple batch
    model_reason: "routine, low-risk"

  - id: feat.new-api
    owner: claude-code
    model: auto                     # let the router decide
```

#### Level 3: Auto-router

When `model: auto` or no model specified, the router picks based on task signals:

```
Input signals:
  - acceptance_criteria count (>3 → higher tier)
  - files_touched estimate (>4 → higher tier)
  - task prefix (feat vs chore vs fix)
  - risk tag if present
  - project default as floor

Decision tree:
  Has explicit model?          → use it
  Is task simple/batch/chore?  → Haiku
  Is task feat with >3 criteria or high-risk? → Opus
  Everything else              → Sonnet (project default)
```

### CLI interface

```bash
# Explicit binding at delegate time
shux delegate feat.auth-redesign --model claude-opus-4-6

# Auto-routing (router picks)
shux delegate chore.update-deps --auto-model

# Set project default
shux config set model.default claude-sonnet-4-6

# Set budget guard
shux config set model.budget.daily_limit 5.00

# View model usage
shux benchmark --models
```

### Dispatch integration

The dispatch engine injects the model into the agent launch command:

```bash
# Claude Code
claude --model claude-opus-4-6 -p "..."

# Codex CLI
codex --model claude-opus-4-6 "..."
```

Each adapter in the adapter registry knows how to pass `--model` to its agent CLI.

### Cost tracking

After dispatch completes, log to ledger:

```yaml
# ledger.md (append)
- task: feat.auth-redesign
  model: claude-opus-4-6
  tokens_in: 45200
  tokens_out: 12800
  cost_estimate: $1.64
  date: 2026-04-06T14:30:00Z
```

Aggregate view via `shux benchmark --models`:

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

### Budget guard behavior

```
Task dispatched with model: claude-opus-4-6
Budget used today: $4.20 / $5.00

→ WARN: Daily budget 84% used. Proceed? [Y/n]

# If over budget:
→ BLOCKED: Daily budget exceeded ($5.12 / $5.00).
  Override with --force, or switch to a cheaper model.
  Suggested: --model claude-sonnet-4-6 (estimated $0.45 vs $2.30)
```

### Design decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where to store model config | `.superharness/config.yaml` | Separate from contract (config vs state) |
| Token counting | Parse agent CLI output (best-effort) | No API key required; agents already print token counts |
| Cost estimation | Hardcoded price table, overridable | Prices change rarely; user can override |
| Budget enforcement | Warn by default, block with `--strict-budget` | Don't surprise users with hard blocks |
| Auto-router location | `src/superharness/engine/model_router.py` | Already exists (from roadmap item 4) |
| Adapter integration | Extend adapter registry with `model_flag` | Each adapter knows its CLI's `--model` syntax |
| Fallback chain | Defer to always-on-agent merge (roadmap item 4) | Don't duplicate; build on existing plan |

### Relationship to existing roadmap

Roadmap item 4 ("Model fallback chain") ports `runner.py` from always-on-agent with fallback logic (`try A → fall back to B → budget guard`). Model binding extends this:

- **Fallback chain** = runtime resilience (model unavailable → try next)
- **Model binding** = dispatch-time selection (right model for the job)
- **Budget guard** = cost governance (don't overspend)

These compose naturally. Build order: model binding (dispatch-time) first, then fallback chain (runtime) on top.

### TDD

```
RED:
  # Model resolution
  test_explicit_model_used                  — task.model set → dispatch uses it
  test_project_default_when_no_task_model   — no task.model → uses config default
  test_auto_router_picks_haiku_for_chore    — chore prefix → haiku
  test_auto_router_picks_opus_for_complex   — >3 criteria + feat → opus
  test_auto_router_defaults_to_sonnet       — no signals → sonnet

  # CLI
  test_delegate_with_model_flag             — --model flag sets task.model
  test_delegate_auto_model_flag             — --auto-model triggers router
  test_config_set_default_model             — shux config set model.default

  # Budget
  test_budget_warn_at_threshold             — 80%+ used → warning printed
  test_budget_block_when_exceeded           — over limit → exit 1 (strict mode)
  test_budget_override_with_force           — --force bypasses block

  # Ledger
  test_dispatch_logs_model_to_ledger        — ledger entry includes model field
  test_benchmark_models_shows_usage         — shux benchmark --models outputs table

  # Adapter
  test_claude_adapter_passes_model_flag     — claude --model X injected
  test_codex_adapter_passes_model_flag      — codex --model X injected

GREEN:
  src/superharness/engine/model_router.py   — extend existing (~150 lines)
  src/superharness/engine/model_budget.py   — new (~100 lines)
  src/superharness/commands/delegate.py     — add --model, --auto-model flags
  src/superharness/commands/config.py       — new: shux config get/set
  .superharness/config.yaml                 — schema with model section
  Extend adapter registry with model_flag per adapter

REFACTOR:
  Merge with roadmap item 4 (fallback chain) when ported
  Consolidate price table with /model-router skill
```

### Files touched

- `src/superharness/engine/model_router.py` (extend, +150 lines)
- `src/superharness/engine/model_budget.py` (new, ~100 lines)
- `src/superharness/commands/delegate.py` (add flags)
- `src/superharness/commands/config.py` (new, ~80 lines)
- `src/superharness/cli.py` (register config command)
- `src/superharness/engine/adapter_registry.py` (add model_flag)
- `tests/test_model_router.py` (new, ~8 tests)
- `tests/test_model_budget.py` (new, ~4 tests)
- `tests/test_delegate_model.py` (new, ~3 tests)

---

## Build Order

```
Phase 1: shux explain          ← quick win, ship first
         (1 session, ~50 LOC)

Phase 2: shux onboard          ← depends on explain (CTA at end)
         (1–2 sessions, ~300 LOC)

Phase 3: model binding         ← independent, can parallelize with phase 2
         (3–4 sessions, ~400 LOC)
```

### Dependencies

```
explain  ──→  onboard (explain's CTA points to onboard)
                │
                ├──→  model binding (onboard could set project default model)
                │
explain  ──→  model binding (explain could mention smart routing)
```

No hard blockers — all three can be built incrementally. `explain` is the obvious first ship.

---

## Success Metrics

| Metric | Before | After |
|--------|--------|-------|
| Time from install to first task dispatched | ~15 min (read docs) | ~3 min (`onboard`) |
| "What is this?" answer | Read README | `shux explain` (10 sec) |
| Model cost waste | Unknown (no tracking) | Visible + budgeted |
| New user drop-off point | After `init` (no guidance) | After `onboard` step 6 (fully set up) |
| Model selection | Manual/advisory | Enforced + auto-routed |
