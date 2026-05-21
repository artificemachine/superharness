# Zero-Touch Adaptive Layer — Behavioral Profile for Superharness

**Date:** 2026-05-21 | **Iteration 4 + 5 of Hermes adaptation**
**Status:** Implemented (Iteration 4) + Improvements in progress (Iteration 5)

---

## Problem

Agents dispatched by superharness know nothing about the user's patterns — coding style, review strictness, trust threshold, model preferences, communication style. Each session starts cold. The user repeats the same corrections.

Superharness already captures all the data needed to build a behavioral profile. It just doesn't synthesize it.

## Architecture

```
┌─ SQLite (existing) ─────────────────────────────────────┐
│ tasks, handoffs, ledger, failures, review_store,         │
│ operator_commands, agent_heartbeats                      │
└─────────────────────────┬───────────────────────────────┘
                          │ watcher queries every N cycles
                          ▼
┌─ Behavioral Profile (NEW) ───────────────────────────────┐
│ ~/.config/superharness/behavioral/                       │
│   task-style.json       ← decomposition patterns         │
│   review-style.json     ← quality bar signals            │
│   model-prefs.json      ← model trust by task type       │
│   autonomy-profile.json ← adaptive trust calibration     │
│   communication.json    ← tone, detail, format prefs     │
└─────────────────────────┬───────────────────────────────┘
                          │ injected into dispatch context
                          ▼
┌─ Agent cold-start context ───────────────────────────────┐
│ "You are working for Max. Style: direct, no emoji.       │
│  TDD required. Prefers effort=medium.                    │
│  Review: strict on tests, lenient on docs.               │
│  Model: opus for architecture, haiku for chores."        │
└──────────────────────────────────────────────────────────┘
```

## Data Sources → Extracted Patterns

| SQLite Table | Signal | Pattern Extracted |
|---|---|---|
| `tasks` | effort distribution, AC count, test_types frequency | Task decomposition style |
| `handoffs` | word count, section usage, code-block ratio | Communication style |
| `ledger` | action types, approval/rejection ratio | Decision patterns |
| `failures` | failure patterns, retry outcomes | Risk tolerance |
| `review_store` | score distribution, failure rate by task type | Quality bar calibration |
| `operator_commands` | approval latency, rejection reasons | Trust threshold |
| `tasks.model_tier` + `delegate --model` | model usage by task effort/type | Model preference |
| `tasks.autonomy` | autonomy level transitions | Adaptive trust |
| `.superharness/memory/` | explicit user teachings | Declared preferences |
| `discussions` | consensus rate, participant count | Collaboration style |

## Adaptive Rules (examples)

| Trigger | Adaptation |
|---------|------------|
| 10 consecutive autonomous tasks succeed | Auto-bump autonomy: `supervised` → `autonomous` |
| 3 consecutive tasks fail on same agent | Downgrade agent trust, suggest fallback |
| User rejects 4 of last 5 plans | Increase plan detail requirement, lower autonomy |
| Task success rate >90% for effort=medium | Default effort → medium, allow auto-approval |
| Reviews scoring >8/10 on last 10 tasks | Relax review gate (skip manual review for known-safe patterns) |
| User never sets `effort=large` | Remove large from default suggestions |
| All failures are `test_failure` pattern | Auto-enable `require_tdd` on tasks |

## Injection Chain (mandatory, not optional)

The profile is NOT a file the agent chooses to read. The watcher injects it into every dispatch's cold-start context via `engine/context_hint.py`, layered between global learning and project memory:

```
1. Global Learning     ← machine-wide patterns from all projects
2. User Profile        ← NEW: extracted behavioral patterns
3. Project Memory      ← per-project conventions
4. Task Context        ← task-specific hints (failures, skills)
```

## Verification

- **Unit:** 1 test per extraction query (does `review_store` produce correct quality signal?)
- **Unit:** 1 test per adaptive rule (does 10 successes trigger autonomy bump?)
- **E2E:** Full cycle — user does 10 tasks → profile updates → next agent sees updated profile
- **Regression:** Profile must degrade gracefully when data is sparse (new user, empty project)

## Implementation Effort

| Component | Effort | Dependencies |
|-----------|--------|-------------|
| Profile extraction queries | 3h | None (SQLite already has data) |
| Profile serialization (JSON files) | 1h | None |
| Context injection (extend context_hint.py) | 1h | Extraction layer |
| Adaptive rules engine | 3h | Extraction + injection |
| Watcher cycle integration | 1h | Rules engine |
| Tests (5 extraction + 5 rules + 2 E2E) | 3h | All above |
| **Total** | **~12h** | |

---

## Improvements (8 design refinements)

### 1. Cold-Start Bootstrap

**Problem:** New users have zero behavioral data. The profile starts empty, defeating the purpose.

**Fix:** The onboarding wizard seeds initial values via 3 lightweight questions:
- *"How strict is your review style?"* → `review-style.strictness` (0.0–1.0)
- *"Preferred level of detail in reports?"* → `communication.detail` (terse/standard/verbose)
- *"Default trust level for agents?"* → `autonomy-profile.default` (approval-gated/supervised/autonomous)

These seeds decay over time as real data accumulates. After 20+ tasks, the seed weight approaches zero and the extracted profile dominates. This prevents the "empty first 10 tasks" problem.

**Implementation:** `shux onboard` gains 3 optional profile questions. Answers written to `~/.config/superharness/behavioral/_bootstrap.json` with `confidence: seed` and `weight: 1.0`. Each watcher cycle decays seed weight by 5%.

### 2. Hysteresis Buffer

**Problem:** Binary thresholds cause oscillation. A user with 50% success rate could bounce between `autonomous` and `supervised` every few tasks.

**Fix:** Add a neutral zone between upgrade and downgrade thresholds.

```
autonomy:
  upgrade:     10 consecutive successes → bump up
  neutral:     4-9 successes, 1-2 failures → stay
  downgrade:   3 consecutive failures → drop down

review strictness:
  relax:       >8/10 average over last 10 reviews, zero failures
  neutral:     5-8/10 average
  tighten:     <5/10 average, or 1+ critical failure (data loss, security)
```

Each adaptive rule has three zones: upgrade, neutral, downgrade. The system only changes state when the signal exits the neutral zone. This prevents flip-flopping on borderline users.

### 3. Exponential Decay (EWMA)

**Problem:** A pattern from 6 months ago has the same weight as yesterday's. If a user changed their style, the profile lags.

**Fix:** Weight each data point by recency using exponential weighted moving average:

```
weight = e^(-age_days / halflife_days)

halflife per signal:
  communication style:   90 days  (slow-changing)
  review strictness:     60 days
  model preference:      30 days  (models evolve fast)
  task decomposition:    45 days
  autonomy calibration:  60 days
```

Old patterns naturally decay. Recent behavior dominates. If a user switches from verbose to terse reports, the profile reflects it within ~2 weeks.

**Implementation:** Every extraction query multiplies by `EXP(-julianday('now') - julianday(created_at)) / halflife)`. The `confidence` score in the profile file is the sum of weights — more data = higher confidence.

### 4. Project vs User Separation

**Problem:** A global behavioral profile overfits to one project's conventions. "Always use ruff" is project-specific, not user-universal.

**Fix:** Split the profile namespace:

```
user.*              ← cross-project, stored in ~/.config/superharness/behavioral/
  user.communication ← direct, no emoji, wants git diff in reports
  user.review        ← strict on tests, lenient on docs
  user.model         ← opus for architecture, haiku for chores
  user.autonomy      ← autonomous after 10 successful tasks
  user.task-style    ← prefers small tasks, TDD required

project.<hash>.*    ← per-project, stored in .superharness/behavioral/
  project.<hash>.conventions  ← ruff, not black. pytest, not unittest.
  project.<hash>.stack        ← Python 3.11+, FastAPI, Postgres
```

The injection layer merges both: user profile first (who you are), project profile second (how this project works). When there's a conflict (user prefers black, project uses ruff), project wins but the profile notes the tension.

**Promotion rule:** If a `project.*` pattern appears identically across 3+ projects, promote to `user.*`. This is the same mechanism as the global memory promotion (Iteration 3).

### 5. Context-Aware Profile Sizing

**Problem:** Opus has 200K context, Haiku has smaller. Injecting the full profile into every dispatch wastes tokens on smaller models.

**Fix:** Generate 3 profile tiers:

| Tier | Size | Content | Used for |
|------|------|---------|----------|
| `summary` | 1-2 sentences | Core directives: TDD required, preferred effort, review style | Always injected (all models) |
| `standard` | 1 paragraph | Summary + model prefs, autonomy level, recent failures | effort=medium, standard models |
| `full` | Full profile JSON + examples | Everything: communication style, historical patterns, skill preferences | effort=max, Opus, big-context models |

The context_hint builder selects the tier based on task effort + model capability. Effort=small gets `summary`. Effort=max + Opus gets `full`. This keeps the injection proportional to the model's capacity.

### 6. Verification Feedback Loop

**Problem:** The system adapts profiles but never checks whether the adaptation improved anything. It could be making agents worse.

**Fix:** After every profile injection, track the next task's outcome and close the loop:

```
FOR each profile change:
  baseline = avg task success rate (last 10 tasks without this profile change)
  test     = avg task success rate (next 5 tasks with this change)

  IF test > baseline + 10%:
    reinforce → profile weight +10%, decay_halflife ×2 (keep longer)
  IF test < baseline:
    revert    → discard profile change, decay_halflife ÷2 (expire faster)
  ELSE:
    neutral   → keep, re-evaluate after 10 more tasks
```

This means every adaptation is A/B tested against actual agent performance. Profiles that help stick around. Profiles that hurt get reverted. The system learns what works.

**Implementation:** A new table `profile_trials` in SQLite tracks: `profile_key`, `old_value`, `new_value`, `baseline_success_rate`, `trial_started_at`, `trial_completed_at`, `outcome` (improved/degraded/neutral). The watcher evaluates trials after 5 tasks.

### 7. User Visibility + Override

**Problem:** Without visibility, the adaptive profile is a black box. The user can't trust what they can't see.

**Fix:** Two CLI commands:

```
shux profile show              # Print current behavioral profile
  --format json                 # Machine-readable
  --explain                     # Show WHY each value was chosen (data source + confidence)

shux profile edit              # Open profile in $EDITOR for manual correction
  --reset <key>                 # Delete a specific extracted pattern (re-learn from scratch)
  --lock <key>                  # Pin a value — never auto-adapt this key
  --unlock <key>                # Allow auto-adaptation again
```

Locked keys are permanent overrides. The adaptive engine skips them entirely. Example: `shux profile edit --lock user.communication.style=direct` means "I always want direct communication, never auto-adapt this."

This also provides a manual override path: if the system learns something wrong, the user can fix it in one command.

### 8. Confidence Scoring

**Problem:** A pattern extracted from 2 data points has the same authority as one from 200. Sparse data leads to overconfident incorrect profiles.

**Fix:** Every extracted pattern carries a confidence score based on sample size:

| Samples | Confidence | How injected |
|---------|------------|-------------|
| < 5 | `low` | Injected as suggestion: *"The system has noticed you may prefer..."* |
| 5–20 | `medium` | Injected as preference: *"Based on your patterns, you prefer..."* |
| > 20 | `high` | Injected as directive: *"Your established pattern is..."* |

Low-confidence patterns never override explicit user settings or locked keys. They accumulate weight via EWMA until they cross the medium threshold.

**Implementation:** `confidence_score = min(sample_count / 20, 1.0)` as a simple linear scale. Each profile key stores its `confidence` and `sample_count`. The injection formatter reads confidence to choose language tone (suggestion vs preference vs directive).

---

## Refined Adaptive Rules (with hysteresis + confidence)

| Trigger | Threshold | Confidence Required | Adaptation |
|---------|-----------|---------------------|------------|
| 10 consecutive autonomous tasks succeed | ≥10 | medium | Bump autonomy up one level |
| 3 consecutive tasks fail on same agent | ≥3 | low | Downgrade agent trust, suggest fallback |
| User rejects 4 of last 5 plans | ≥5 | medium | Lower autonomy, increase plan detail |
| Task success rate >90% for effort=medium (EWMA, halflife 45d) | >90% | high | Default effort → medium, auto-approve |
| Reviews scoring >8/10 on last 10 tasks | ≥10 | medium | Relax review gate |
| All failures are `test_failure` pattern (last 10) | ≥10 | medium | Auto-enable `require_tdd` |
| Model X has >20% higher success rate than model Y for same task type | ≥20 samples | high | Update model preference |
| User never uses `effort=large` in last 50 tasks | ≥50 | high | Remove large from defaults |

---

## Summary of Improvements

| # | Improvement | Solves | Mechanism |
|---|-------------|--------|-----------|
| 1 | Cold-start bootstrap | Empty profile for new users | Onboarding seeds + decay |
| 2 | Hysteresis buffer | Oscillation on borderline users | 3-zone thresholds |
| 3 | Exponential decay | Stale patterns dominating | EWMA with per-signal halflife |
| 4 | Project/User separation | Overfitting to one project | `user.*` vs `project.<hash>.*` |
| 5 | Context-aware sizing | Wasting tokens on small models | 3-tier injection (summary/standard/full) |
| 6 | Verification loop | No feedback on adaptation quality | A/B test every profile change |
| 7 | User visibility + override | Black-box distrust | `shux profile show/edit` with lock |
| 8 | Confidence scoring | Sparse data overconfidence | Low/medium/high tiers with language tone |

---

## Iteration 5 — Production Hardening (4 improvements)

### I5.1: Deduplicate Global Memory

**Problem:** Promoted patterns accumulate duplicates. Same pattern "SIGKILL leaves stale lock dirs" appears 4 times in Global Learning because 4 projects promoted it independently. Wastes tokens and reduces signal-to-noise.

**Fix:** In `get_dispatch_memory_context()`, collapse identical lines with a count:
```
2026-05-20: SIGKILL leaves stale watcher lock dirs (seen 4 times)
```
Implementation in `engine/agent_memory.py:_read_memory_file()` — use Counter, show count for lines appearing >1 time. Single occurrences unchanged.

### I5.2: Wire Profile Extraction into Watcher Cycle

**Problem:** Profile only updates when `context_hint.py` is called (dispatch time). If no tasks dispatch for hours, the profile goes stale. Should refresh periodically like memory promotion does.

**Fix:** Add `_refresh_behavioral_profile()` to `inbox_watch.py` watcher cycle. Runs every N cycles (default 5). Calls `extract_all_profiles()`, saves results to `~/.config/superharness/behavioral/`. Idempotent — only writes if data changed since last extraction.

### I5.3: Auto-Apply Adaptive Rules

**Problem:** `evaluate_rules()` detects `bump_autonomy` but the watcher never acts on it. The rules engine is analytics-only, not action.

**Fix:** After profile refresh, evaluate rules. If triggered:
- `bump_autonomy` → update `profile.yaml` autonomy field, write ledger entry
- `lower_autonomy` → downgrade `profile.yaml`, write ledger entry with reason
- `enable_tdd` → set `require_tdd: true` on new tasks
- `set_default_model` → update `profile.yaml default_model`
- `relax_review` → update review gate settings

Each adaptation writes a ledger entry so the user can trace why autonomy changed.

### I5.4: Auto-Record Reviews on Task Close/Verify

**Problem:** `review_style` profile always shows `0 reviews` because nothing populates `review_store`. Every task close should seed review data so the profile learns.

**Fix:** In `state_writer.py:set_task_status()` — when status transitions to `done` or `review_passed`, auto-record a review entry: score=10 for `done` (success), score based on verification for other statuses. Also in `commands/verify.py` and `commands/close.py` — write to `review_store`.

## Implementation Plan (Iteration 5)

| # | Component | Effort | Tests |
|---|-----------|--------|-------|
| I5.1 | Deduplicate global memory | 20 min | 2 tests |
| I5.2 | Watcher profile refresh | 30 min | 2 tests |
| I5.3 | Auto-apply adaptive rules | 1h | 3 tests |
| I5.4 | Auto-record reviews | 1h | 2 tests |
| **Total** | | **~3h** | **9 tests** |
