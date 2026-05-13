# Plan: Ralph Loops extraction into superharness

Status: proposal — not yet planned via `shux task create`
Date: 2026-05-09
Source intel: vault `notes/1_ai/youtube_intel/intel/ralph_loops_dumb_ai_loops_that_ship`
Workshop: <https://youtu.be/2TLXsxkz0zI> (Chris Parsons / Cherrypick)

---

## Review findings (2026-05-09, post-verification against codebase)

The thesis holds — superharness is structurally Ralph-shaped already. But the specifics below have factual issues that change effort estimates and acceptance criteria. Read this section before opening any task.

### Wrong file pointers in Extract 1

The plan points at `engine/discussion.py` for review-dispatch wiring. **That's the multi-agent discussion feature, unrelated.** Actual review wiring:

- `src/superharness/commands/inbox_watch.py:_select_reviewers` (line 808) — picks who reviews
- `src/superharness/commands/inbox_watch.py:_trigger_auto_review` (line 829) — transitions to `review_requested` and enqueues reviewers
- `src/superharness/commands/delegate.py` — accepts `--for-review` flag (line 1282), no separate "reviewer template"

### Extract 1's premise may already be solved at the process level

Three pre-existing facts matter:

1. **Cross-pollination guard already enforces implementer ≠ reviewer.** `inbox_watch.py:819`:
   ```python
   peers = [a for a in candidates if a != owner]
   ```
2. **Model-tier gate already filters reviewers.** `inbox_watch.py:814` calls `reviewer_meets_tier(a, author_tier, profile)`.
3. **Adapter scripts have no session continuation.** `delegate-to-claude.sh`, `delegate-to-codex.sh`, `delegate-to-codex.sh`, etc. — none of them pass `--continue` / `--resume` / `--session-id`. Every dispatch is a fresh process.

So when peers exist, the implementer's chat history is already not visible to the reviewer. The Ralph workshop's confirmation-bias defect surfaces specifically when the *same* agent reviews itself, which superharness already prevents.

**Where the gap actually lives:** what happens when `_select_reviewers` returns `[]` (no peers, or all peers fail tier gate)? Today there's a fallback path. *That* is the real Extract 1.

Reframe Extract 1 acceptance criterion 1 to:
> When `_select_reviewers` returns no peers, the system MUST [either] (a) hold the task in `review_requested` waiting for operator, [or] (b) launch a fresh-context same-agent reviewer with explicit history-stripped prompt — pick one. Today behavior is undocumented.

### Extract 3 conflates two priority surfaces

`PRAGMA table_info(tasks)` shows **no `priority` column on the tasks table.** Priority lives only on `inbox`. The dispatch path is two-stage:

1. **Task selection** (`auto_dispatch.py`): `todo` tasks → enqueue. Currently FIFO by `created_at`. **Cannot order by priority — column does not exist.**
2. **Inbox dequeue** (`inbox_dao.claim_next`): correctly uses `ORDER BY priority DESC, created_at ASC`. ✅ Already works.

So Extract 3's acceptance criterion 1 ("two unblocked todos with different priorities — dispatch picks higher priority") **will fail** because there's no priority field on todos to sort by.

Decision required before opening: either
- **Add `tasks.priority` column** — schema migration v12. Promotes Extract 3 from "<1 day" to "schema migration + classifier integration ~2 days."
- **Document FIFO at todo selection, priority only at inbox dequeue** — acceptance criterion 1 becomes about inbox priority instead. ~30 minutes.

### Extract 2 should use `extras_json`, not a new column

Schema v11 (just shipped 2026-05-09) added `tasks.extras_json` for nested per-task metadata (subtasks, classifier, decomposer, retry). `reversibility` fits the same pattern. **Adding another column when `extras_json` exists breaks the schema-stability principle.**

Reframe Extract 2 touchpoints:

- ❌ ~~Schema migration: `tasks.reversibility` column~~
- ✅ Store `{"reversibility": "reversible"|"irreversible"}` in `tasks.extras_json`
- ✅ `state_reader._tasks_from_sqlite` already merges extras_json into the task dict (line ~232)
- ✅ Read via `task.get("reversibility")` in `auto_dispatch.py` and `inbox_watch.py`

That collapses the schema part of the work. Migration goes from "v12 column add + backfill" to "zero schema work, just a JSON key convention + classifier defaults."

### Autonomy is three-way, not binary

Plan says: "the policy is binary (autonomous / oversight / ai_driven)". Three values is three-way. Minor wording, but Extract 2's gate sits *across* the autonomy axis (every cell of `autonomy × reversibility`), not as a replacement for autonomy. Worth being precise so the matrix is explicit when the rule file gets written.

### Open question 2 has an obvious answer

Plan asks: "should default classifier rules be a project-level overridable list, or hard-coded heuristics?"

`.superharness/rules/` shipped 2026-05-07 (rules system) for exactly this. Hard-coded heuristics would break the pattern. Answer: rules file with `is_irreversible: <pattern>` lines, default ships in `init_project`, project can override.

### Recommendation before any task is opened

1. **Resolve Extract 3 schema decision** (add column vs document FIFO). 2-line decision, flips the effort estimate.
2. **Verify Extract 1's premise** — grep audit logs / ledger for "no reviewers selected" or `_select_reviewers` returning `[]`. If never hit in production, Extract 1 is theatre and effort drops to "document the no-peer fallback."
3. **Refit Extract 2** on `extras_json` instead of new column. Saves a schema migration.
4. **Fix file pointers** in Extract 1 (above).

After those four, the plan is ready for `shux task create`.

---

## TL;DR

superharness already implements ~80% of Ralph Loops in disguise. `auto_dispatch` runs continuously inside the watcher (`inbox_watch.py`), gated on `profile.auto_dispatch=true` + `autonomy in (autonomous|ai_driven|oversight)`. The six auto-mode lifecycle rules cover the rest of the "next most important task, do it, repeat" pattern.

The remaining 20% is one targeted extension and one workflow-policy field. Do not bolt on a raw Ralph runner.

---

## Why a raw Ralph runner is wrong here

Parsons-style Ralph is `while true; do claude -p "implement next ticket"; done` (or the in-session `loop every <interval>` cron). Bolting that on top of superharness fails for one structural reason: the lifecycle gates.

A pure Ralph loop wants no pauses. Superharness deliberately stops at:

- `plan_proposed → plan_approved` — operator approves the plan
- `report_ready → done` — operator closes (or `review_requested → review_passed → done`)

Those gates are the protocol. They're what prevent the harness from shipping bad work autonomously. A raw Ralph runner either:

1. **Bypasses them** — defeats the protocol's whole purpose.
2. **Deadlocks waiting on them** — defeats the loop.

Resolution is structural: make superharness *more* Ralph-shaped *between* the gates. Don't add a Ralph layer on top.

---

## What superharness already has (no work needed)

| Ralph idea | superharness equivalent |
|---|---|
| Continuous "next task" loop | `auto_dispatch` in watcher loop (`inbox_watch.py`) |
| "Pick next most important" prompt | task priority + `blocked_by` resolved by dispatch |
| Fresh-context discipline | report handoff + per-dispatch adapter context reset |
| `loop every <interval>` cron | `shux schedule` |
| Auto-classify and route | `auto_dispatch` classifier → adapter selection |
| Stale-task escalation | 6 auto-mode lifecycle rules (3h/8h/24h/2h/deadline/review) |

Verified by reading `src/superharness/commands/inbox_watch.py` and the `shux` CLI surface.

---

## What's worth extracting (the 20%)

### Extract 1 — Sub-agent reviewer for `review_requested` (HIGHEST LEVERAGE)

**Source:** workshop audience finding, validated live by Parsons. When the validation step runs in the same context as the implementer, it rubber-stamps. Switching to a fresh sub-agent immediately starts catching defects.

**Today in superharness:** the `review_requested` transition can route the review to the same adapter / context that produced the work. Confirmation bias is unmitigated.

**Change:** when a task transitions to `review_requested`, the watcher dispatches the reviewer in a **fresh sub-context** with no implementer history. Inputs: the task spec, the `review_requested` handoff, the diff. Nothing else from the implementer's session.

**Concrete touchpoints:**

- `engine/discussion.py` or wherever the review dispatch is wired (`grep -rn "review_requested" src/`)
- Reviewer adapter prompt template — must not pull in the implementer's session
- Test: same-context review accepts a planted defect; sub-agent review rejects it

**Acceptance criteria:**

1. `review_requested` always launches a brand-new adapter session with no chat history from the implementer.
2. Reviewer receives only: task definition, plan handoff, report handoff, code diff, project rules.
3. Unit + e2e test demonstrating the confirmation-bias defect class is caught.
4. Backwards compatible — existing tasks that skip review (`report_ready → done` direct close by operator) unchanged.

**Effort:** small to medium. Probably 1–2 days. <4 files. Single acceptance criterion cluster — does not require `shux delegate --orchestrate` decomposition.

**Risk:** review latency increases slightly (fresh adapter cold-start). Mitigation: keep reviewer dispatches asynchronous, never block the dispatcher.

---

### Extract 2 — "Reversible without embarrassment" autonomy gate (MEDIUM LEVERAGE)

**Source:** Parsons' worker-loop guardrail. *If this action is reversible without embarrassment to me, do it; otherwise stop and hand back.* Drafting an email = autonomous. Sending the email = blocked.

**Today in superharness:** `shux workflow` has autonomy fields, but the policy is binary (autonomous / oversight / ai_driven) at the project level. Per-task or per-action reversibility is not first-class.

**Change:** add a `reversibility` classification to tasks (or to adapter capabilities). Values: `reversible | irreversible`. `auto_dispatch` may fire `reversible` tasks without human approval; `irreversible` tasks always force a `plan_proposed` stop regardless of project autonomy.

**Concrete touchpoints:**

- `shux task create` — add `--reversibility {reversible,irreversible}` flag (default: `reversible` for chore/docs/test, `irreversible` for release/migration/external-effect tasks)
- Task classifier in `auto_dispatch.py` — infer from task title/content if not set
- Lifecycle gate in `inbox_watch.py` — `irreversible` tasks cannot skip `plan_approved`
- `.superharness/rules/reversibility-gate.md` — new rule file
- Schema migration: `tasks.reversibility` column

**Acceptance criteria:**

1. New schema column with default classifier behavior.
2. `irreversible` task cannot transition past `plan_proposed` without an explicit `plan_approved` operator action.
3. `reversible` task can be auto-dispatched end-to-end when project autonomy allows.
4. Rule file added and surfaced via `shux rules`.

**Effort:** medium. Schema migration + classifier + 1 rule file + tests. ~1 week.

**Risk:** classifier mis-labels things. Mitigation: default to `irreversible` on ambiguity (fail safe), let operator downgrade.

---

### Extract 3 — Priority-ordered dispatch (SMALL CLEANUP)

**Source:** Parsons' "implement the *next most important* ticket". Dependency graphs were a failure; priority + `blocked_by` is the working pattern.

**Today in superharness:** tasks have `blocked_by` and `priority` fields; verify `auto_dispatch` actually orders by priority and not by insertion order.

**Change:** audit the dispatch query path. If priority is ignored, fix the SQL ordering. If priority is honored, document it in `docs/ARCHITECTURE.md` so the contract is explicit.

**Concrete touchpoints:**

- `src/superharness/commands/auto_dispatch.py` (the actual dispatch loop)
- `state_reader.py` — task selection query
- `docs/ARCHITECTURE.md` — document selection ordering

**Acceptance criteria:**

1. Test: two unblocked todos with different priorities — dispatch picks higher priority, regardless of insertion order.
2. Tie-break documented (oldest? alphabetic?).

**Effort:** small. <1 day if the fix is just `ORDER BY priority DESC, created_at ASC`.

**Risk:** none material.

---

## What we deliberately do not extract

- **Raw `while true; claude -p` runner.** Conflicts with the watcher, bypasses gates. See "Why a raw Ralph runner is wrong here" above.
- **Skip-the-plan, just-loop simplification.** TDD plan + review gates stay. The cost of a bad task at scale is higher than the cost of a plan handoff.
- **Cron-based `loop every X` slash command.** `shux schedule` already exists.

These already live in `ATTRIBUTIONS.md` under "Did not adopt" for the Ralph row.

---

## Sequencing

Recommended order if all three are done:

1. **Extract 3 first** — small audit, clears the priority question before the bigger work touches dispatch.
2. **Extract 1** — sub-agent reviewer. Highest user-visible value. Independent of Extract 2.
3. **Extract 2** — reversibility gate. Larger surface area; do it once Extract 1 is shipping cleanly.

Each extract should be its own task in `shux task create`, with this doc linked from the plan handoff. Extract 1 fits a single task. Extract 2 should likely be decomposed (schema migration → classifier → CLI flag → rule file → tests) per the `task-scope` rule.

---

## Open questions for the operator

1. Does Extract 3 already work and we just need a doc, or is dispatch FIFO?
2. For Extract 2, who owns the default classifier rules — should it be a project-level overridable list, or hard-coded heuristics?
3. Extract 1: should `review_requested` always force a fresh sub-agent, or only when the implementer adapter == reviewer adapter? (Cross-adapter review is already partially fresh.)

Answer these before opening tasks.

---

## References

- `ATTRIBUTIONS.md` — Ralph Loops row (long form, with Adopted / Did not adopt)
- `README.md` — Prior art and influences section
- `protocol/spec.md` — current lifecycle states
- `docs/auto-mode-gap.md` series — historical context for auto-mode
- `src/superharness/commands/inbox_watch.py` — watcher dispatch loop (where Extracts 1 and 2 land)
- `src/superharness/commands/auto_dispatch.py` — todo classifier (where Extract 3 lands)
