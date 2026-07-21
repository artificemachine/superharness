# COMPARE — LTX-2 `train-model` skill vs the superharness lifecycle

Date: 2026-06-25
Source intel: vault note `ltx2_ingredients_iclora_ref2video` + Lightricks LTX-2 `.claude/skills/train-model/`
Purpose: structural side-by-side, and what (if anything) is worth importing into superharness

---

## TL;DR

They look similar on the surface (gates, plan-before-work, honesty invariants) but operate at **different layers and via different enforcement mechanisms**:

- **LTX-2 skill** = a declarative *playbook*: `SKILL.md` + `phases/*.md` an agent reads and executes top-down. Gates are **persuasive prose** the agent is told to obey.
- **superharness** = an enforced *state machine*: a single transition table (`engine/next_action.py::_MAPPING`) validated on **every** DB write (`state_writer.set_task_status` → `validate_status_transition`), plus dispatch/close gates and a timer-based reconciler. Gates are **mechanical** — illegal writes are rejected (exit code 2 permanent block).

They are **complementary, not competing**: superharness is the outer orchestrator (which task, who runs it, when, did it pass). The LTX-2 skill is an inner per-task playbook (how to execute one complex job well). You could run the train-model skill *as* a superharness task.

---

## Side-by-side

| Dimension | LTX-2 `train-model` skill | superharness |
|---|---|---|
| Form | Markdown phase files (`SKILL.md`, `phases/prepare-dataset.md`, `preprocess-dataset.md`, `launch-and-monitor.md`, `post-train-validate.md`) | Code: `next_action._MAPPING` transition graph + `state_writer` + `lifecycle_rules` reconciler |
| Unit of progress | Phase (0–9), narrated in prose | Task status in SQLite (`todo → plan_proposed → … → done`) |
| Plan/approval gate | Phase 4 plan approval before heavy work (prose: "heavy work cannot start until plan approval") | `delegate.py` Gate 5: implementation dispatch of unapproved task → `EXIT_PERMANENT_BLOCK`; contract locked (AC+tdd frozen) on `plan_approved` |
| Enforcement | Agent obedience to instructions | Mechanical: `validate_status_transition` rejects illegal writes; gates return exit code 2 |
| Stall recovery | None — if the agent stalls mid-phase, nothing reconciles | Timer daemon: `in_progress` 3h → archive, `report_ready` 24h → archive, per-task deadlines, review escalation (`lifecycle_rules.py`, `review_escalation.py`) |
| Scope | Single agent, single training run | Cross-agent contract (claude-code/codex/gemini/opencode), handoff schemas, reviewer chain |
| Honesty invariants | "no silent assumptions", "never fabricate training outcomes", "ETA only when grounded in real emitted step timings" | `report_verifier` requires `outcome`>20ch, `context`, `tests_passed:true`, referenced files exist on disk; "never self-close"; "status via CLI not YAML" |
| Source of truth | The run workspace (`<workspace>/<run-name>/`) + `plan.md`, `config.yaml` | SQLite (`.superharness/state.db`); YAML is export-only/DEAD |

---

## Where they genuinely converge (validation, not action)

- **Plan/approval gate before expensive work.** LTX-2 Phase 4 ≈ superharness `plan_proposed → plan_approved`. Both refuse to start heavy work without sign-off.
- **Report/inspect before "done."** LTX-2 Phase 9 hands renders to the user to judge; superharness `report_ready` → operator review/close. Neither lets the worker declare success unilaterally.
- **Honesty-as-invariant.** LTX-2's "never fabricate outcomes / no silent assumptions" ≈ superharness `report_verifier` + the project's global Rule 18. A funded lab encoding the same guardrails is external validation that these aren't personal pedantry.

This convergence is the headline from the intel note. It does **not** require any superharness change.

---

## What the LTX-2 skill does that superharness doesn't (steal candidates)

These are **inner-loop guardrails** — patterns for how an agent executes a single complex task. superharness gates lifecycle *boundaries*; it says little about behavior *inside* an `in_progress` task. Candidates to encode as agent-instruction defaults or `.superharness/rules/*.md`:

1. **Spot-check N before full batch.** Phase 5 captions 3 samples, shows them in full, and hard-stops for approval before captioning the whole dataset. Phase 6 preprocesses one sample before the full latent cache. superharness has no "cheap-sample gate before expensive-batch" pattern within a task. Worth a rule for any batch/migration task: *prove on a small sample, get sign-off, then run the batch.*

2. **No-fabricated-progress, explicitly.** "ETA only when grounded in real step timings the trainer has actually emitted; exclude setup overhead." `report_verifier` checks final artifacts but doesn't forbid invented progress narration mid-task. Import the wording as an agent-instruction default.

3. **Surface silently-dropped items.** Phase 7 reconciles latent count vs sample count and STOPs if fewer were produced ("process_dataset.py silently skips short clips"); the audio gate STOPs if `audio_latents/` is empty ("the tool swallows decode errors and continues"). This is "no silent caps/omissions" made concrete with count reconciliation. A good rule: *after any batch step, reconcile produced-count vs expected-count and report the delta before proceeding.*

4. **Mid-execution decision gates via `AskUserQuestion`.** On a data conflict (existing `.precomputed/`), the skill offers reuse / re-version / abort rather than guessing. superharness decision points inside a task are agent-discretionary. A pattern worth encoding: *on a destructive-or-ambiguous fork inside a task, present an explicit 3-way choice, don't infer.*

5. **Forbidden-verdict discipline.** Phase 9 forbids the agent from judging pass/fail, suggesting fixes, or coaching — the user inspects, the agent exits. An interesting inversion: the agent is told to do *less*. Relevant to constraining superharness reviewer over-reach (a reviewer task that fixes instead of reviewing is scope creep).

---

## What superharness does that the skill doesn't (don't regress)

1. **Enforcement, not just instruction.** The skill relies on the agent obeying prose; superharness mechanically rejects illegal transitions. Don't water superharness gates down to "guidance."
2. **Self-healing via the timer reconciler.** The skill has no daemon — a stalled run sits forever. superharness archives/fails stuck states on a timer. This is a real capability gap in the skill, not something to copy from it.
3. **Contract lock on approval.** `plan_approved` freezes AC+tdd into `locked_contract` (released only on `review_failed`). Prevents post-approval scope drift. The skill re-derives `plan.md` but doesn't lock it.
4. **Cross-agent handoffs + reviewer escalation.** Multi-agent contract, handoff schemas, review-chain escalation to operator. The skill is single-agent/single-run.

---

## The actual insight

The two are at **different layers**:

```
superharness  → OUTER loop: which task, who runs it, when, gates, did it pass, handoff
LTX-2 skill   → INNER loop: how to execute ONE complex task as well-gated phases
```

You could literally run the LTX-2 `train-model` skill *as the body of* a superharness task: superharness owns `plan_proposed → … → done` and the timer reconciler; the skill owns the in-task phase discipline. The steal list above (1–5) is exactly the inner-loop guardrail vocabulary superharness currently leaves to agent discretion.

---

## Recommendation

- **No lifecycle change.** The convergence is validation, not a gap.
- **Optional, low-cost:** capture steal-candidates 1–3 (spot-check-before-batch, no-fabricated-progress, surface-dropped-items) as `.superharness/rules/*.md` entries or as default agent-instruction lines — these are inner-loop guardrails superharness doesn't currently express and they cost nothing to state.
- **Skip** copying the skill's phase-file structure into the lifecycle itself. superharness's enforced transition table is the stronger mechanism; phase files are a per-task playbook concern, which is what `.superharness/skills/` (the loader, already present) is for if you ever want it.
