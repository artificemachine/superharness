# HANDOFF — 2026-06-07 Deep Audit: why task/discussion create/manage fails

> ✅ **COMPLETED — full verified audit:** `docs/AUDIT-2026-06-07-task-discussion-failure.md`
> The audit was re-run to completion after the Opus limit reset: **67/67 findings verified real, 0 false positives** (verify on Sonnet, synthesis on Opus). The full report supersedes the hand-written synthesis below. This file is kept as the session handoff + the parts reproduced first-hand. The full run surfaced an additional HIGH task-side root cause not in the first pass (see "Correction" below).
>
> **Branch:** main
> **Trigger:** Owner reported discussions never reach consensus and task management is unreliable despite many hours of dev.
> **Method:** Multi-agent audit (workflow `wf_449590c4-f7e`): 6 mappers → 7 adversarial hunters → 67 per-finding verifiers → 1 synthesizer. Two passes, ~162 agent-runs, ~8.6M tokens.
> **Confidence:** Discussion root cause (A/B) reproduced first-hand on this machine (prompt files written with model-name content, no consumer). Task-side root cause (E) and data-layer (D/H) verified by code inspection.

## Correction / addition from the full run (was missing in the first pass)

**Task-side primary block:** `shux init` never writes `auto_dispatch` to profile.yaml (`init_project.py:93-100`), so every auto-enqueue/dispatch path early-returns (`inbox_watch.py:617,2050,2162`). And a default `todo` + `implementation` task fails Gate 5 as a **non-retryable permanent block** at `delegate.py:709-734` (`todo` ∉ `allowed_statuses_for_workflow("implementation")`, `next_action.py:224-236`) → rc=2 → retries pinned to max → inbox item permanently dead. This IS the "permanent block (lifecycle gate)" message. Also: `autonomy` is a dead gate — `normalize_autonomy` collapses every value (incl. `supervised`) to `ai_driven` (`profile.py:34-47`) while `pipeline_check.py:44-45` reads the raw value, so diagnostics and runtime disagree.

---

## Bottom line

The discussion subsystem has **no executor**. `shux discuss start` enqueues round items; the watcher writes a `.prompt.md` file, marks the item `dispatched`, and **never spawns an agent** ("session-injection" mode). Nothing installed on this machine reads those prompt files, and the file content is wrong anyway (it embeds the model name `claude-opus-4-8`, not the topic). So every round is a silent no-op that times out as `failed_participant`. The component that *would* run an agent with the correct prompt (`delegate`) is deliberately bypassed for discussions. Task management is separately degraded because dispatch reconciliation reads completion from the **dead `contract.yaml`**, recording successful tasks as `failed`. Underneath both: ~5 divergent DB-path resolvers and a confirmed (currently benign) two-DB split-brain.

---

## The broken critical path — `shux discuss start` → `failed_participant`

1. `discuss.py:180-239` resolves owners (all 4 PRIMARY_AGENTS) and checks per-agent heartbeats. **Nothing writes per-agent heartbeats on a schedule**, so they are always stale → start requires `--force` (Finding #5). With `--force`, quorum is illusory: no agent will ever respond.
2. Round-1 inbox items enqueued per agent.
3. Watcher claims each item and calls `inbox_dispatch` with `--session-inject` (always appended, `inbox_watch.py:482`).
4. `inbox_dispatch` sees `is_discussion=true` (substring `/round-` on the task id, `:1572`) → `_write_discussion_prompt_file` writes `.superharness/discussions/<id>/round-1-<agent>.prompt.md` whose **"Original Dispatch Prompt" is `launch_args[-1]` = a delegate CLI flag = the model name** (`:1372-1383, 1718`, Findings #3/#6), then marks the item `dispatched` (`:1413-1419`, Findings #4/#8).
5. **No agent process is ever spawned** (`:717-725`, Findings #1/#2). `delegate.py:1005-1025` already builds a correct, topic-aware prompt and would launch the agent, **but session-inject bypasses delegate entirely** (Finding #9).
6. Nothing reads the prompt file — the claude-code superharness plugin/hooks are not installed (`shux doctor` warns), so there is no consumer (Finding #1).
7. Re-dispatch is impossible: `_already_session_injected` keys on prompt-file existence, not verdict (`:1430-1450`, Finding #14); the orphan-advance reconciler requires inbox status `done`, never reached (`inbox_watch.py:3318-3322`, Finding #13); `dispatched` has no timestamp and no reconciler (Findings #4/#8).
8. After grace, the deadlock GC closes it (fires at 30 min but prints "no engagement after 2+ hours" — misleading, `inbox_watch.py:4014, 4026-4040`, Finding #30).
9. **Result: 0 verdicts, every time.**

Even if agents ran, consensus accounting is internally contradictory: three different consensus definitions (`discussion.py:201-210` vs `470-486` vs `391-393`, Finding #16); premature consensus on n-1 submissions (`:198-217`, Finding #17); a single stale lifecycle-gate block on one agent (e.g. gemini-cli) poisons **all** discussions because `_agent_available` has no task_id filter (`discussion_dispatch.py:132-144`, Findings #15/#26); `--max-rounds` is silently ignored (hardcoded 3, Finding #29); effort-deadline auto-close passes `--reason` to a `close` command that rejects it, exits 2 (Finding #19).

## The broken critical path — normal task dispatch

- Dispatch reconciliation reads completion status from the **dead `contract.yaml`**, so successful tasks are recorded `failed` (`inbox_dispatch.py:862-895`, Finding #7).
- `--for-review` is also derived from `contract.yaml`, so review re-dispatches never carry the review flag to the agent (`:1486-1495`, Finding #10).
- Three divergent task-status write paths; the **documented CLI path (`task.py:515`) does no transition validation**, MCP path bypasses create-time validation (`mcp/tools/contract.py:44-103`, Findings #12/#28).
- No reconciler timeout for `plan_approved`/`plan_proposed`/`pending_user_approval` → wedged tasks never auto-recover (`lifecycle_rules.py:46-126`, Finding #27).
- A normal task whose id contains `/round-` or starts with `discuss-` is silently session-injected and never run (substring match, `:1572`, Finding #21).

---

## Root causes (ranked)

**A. Discussions have no working executor (CRITICAL).** Findings #1, #2, #9, #3/#6, #5, #4/#8, #14, #13, #30. Session-injection writes files nobody reads, with wrong content, and never launches an agent. `delegate` already does it right and is bypassed.

**B. Consensus/quorum logic is internally contradictory (HIGH/MEDIUM).** Findings #16, #17, #15/#26, #29, #19. Even with live agents, outcomes are non-deterministic and one stale block poisons all discussions.

**C. Task dispatch trusts a dead data source (HIGH).** Findings #7, #10, #12, #28, #27, #21, #35. Reconciliation and review flags read `contract.yaml` (retired in favor of SQLite); multiple inconsistent status writers.

**D. Data-layer resolver sprawl + split-brain (HIGH→LOW, mostly latent).** Findings #11, #22, #23, #24, #25, #18, #31, #32, #33, #34. ~5 DB-path resolvers that disagree; live two-DB coexistence (XDG live, legacy empty shadow); writer honors `SUPERHARNESS_STATE_PROJECT` but readers do not (in-process split during worktree dispatch — *inferred*, not reproduced).

**E. Errors are swallowed (MEDIUM).** Finding #20. Dispatch is spawned detached to `DEVNULL` with no rc check; `discussion_dispatch` is wrapped in `except: pass`. This is *why* it fails with no visible error.

---

## Fix plan (prioritized, TDD-oriented)

**MINIMUM VIABLE FIX (makes a discussion actually reach consensus):**
1. **Route discussion rounds through `delegate` instead of session-inject** — stop appending `--session-inject` for discussion rounds in `inbox_watch.py:482`; let `inbox_dispatch` spawn the agent via `delegate` (which builds the correct topic-aware prompt, `delegate.py:1005-1025`). RED: a test that runs one round end-to-end and asserts a verdict row appears in `discussion_rounds`. Effort: **M**.
   - *Alternative if session-injection is intentional:* (a) write the real topic into the prompt file (not `launch_args[-1]`), (b) ship + install a consumer hook in the claude-code adapter, (c) add a scheduled per-agent heartbeat writer. Effort: **L**. The delegate route is simpler and reuses working code.

**Then:**
2. Fix dispatch reconciliation to read completion from SQLite, not `contract.yaml` (`inbox_dispatch.py:862-895`, `:1486-1495`). RED: dispatched task that succeeds is recorded `done`, not `failed`. Effort: **M**.
3. Make `dispatched` a real state: add `dispatched_at`, a reconciler timeout, and allow re-enqueue (`inbox_dao.py`, `inbox_watch.py`). Effort: **M**.
4. Collapse the 3 consensus definitions into one; fix n-1 premature consensus (`discussion.py:198-217, 201-210, 470-486`). RED: identical inputs → identical verdict; n-1 never declares consensus. Effort: **M**.
5. Scope `_agent_available` lifecycle-block to (task_id, time-window) so one stale block can't poison all discussions (`discussion_dispatch.py:132-144`). Effort: **S**.
6. Unify task-status writers behind one validated path; route MCP + CLI through it (`task.py:515`, `mcp/tools/contract.py`). Effort: **M**.
7. Replace substring `is_discussion` with an explicit type/flag on the inbox row (`:1572`). Effort: **S**.
8. Surface dispatch failures: capture rc, log non-zero, drop the bare `except: pass` (`inbox_watch.py:488-489, 2664-2666`). Effort: **S**.

**Latent (D-group), do as a batch:** consolidate the ~5 DB-path resolvers into one helper that honors `SUPERHARNESS_STATE_PROJECT` + realpath consistently; make `doctor` detect a two-DB split and `migrate-state` merge it; fix dashboard hardcoded legacy path (`dashboard-ui.py:1616`); delete/again-route the zero-caller `resolve_state_db_path` footgun (`paths.py:34-36`). Effort: **L**.

---

## What is NOT verified (honesty / Rule 18)

- Verify phase confirmed 35/67 findings before rate-limit; ~26 findings could not be machine-verified this run and were excluded from the confirmed set. They may still be real — re-run verify after the session limit resets (3:20pm Madrid) to clear them.
- D-group worktree/env split paths (#23, #25) are inferred from code inspection, not reproduced on disk.
- Root cause A and the prompt-file/model-name bug were reproduced first-hand on this machine.

## Reproduction artifacts
- Live discussion that failed: `discuss-20260607T082510Z-9066-405849218` (0/4 verdicts).
- Prompt file with wrong content: `.superharness/discussions/discuss-20260607T082510Z-9066-405849218/round-1-claude-code.prompt.md`.
- Two DBs: live `~/.local/state/superharness/e23fb9d706f7/state.db` (1696 inbox rows) vs empty `.superharness/state.sqlite3` (0 rows).
- Workflow run: `wf_449590c4-f7e` (81 agents, 5.27M tokens).
