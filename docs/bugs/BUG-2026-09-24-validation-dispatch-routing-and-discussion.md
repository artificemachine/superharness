# BUG 2026-09-24: end-to-end validation of v1.86.3, dispatch routing, lifecycle and discussion defects

**Severity:** critical. No task dispatched to a non-Claude agent can complete, a successful Claude run loses its committed work, and closing a discussion rewrites failures as successes.
**Status:** open. Observed once on v1.86.3 (pipx install, macOS), 2026-09-24T09:53Z to 10:23Z. Each finding below is from a single run; none was reproduced a second time.
**Scope:** 25 findings: 2 critical, 6 high, 10 medium, 7 low. Grouped below by the code path they share.

## How the run was set up

- A throwaway git project with one Python package and one pytest test, `shux init`, sandbox daemon running (interval 30s).
- Agents: claude-code, codex-cli, opencode, pi. Gemini was out of scope.
- One task per agent (`plan_approved`, owner = that agent), one four-agent discussion, a set of failure-path probes, and the status/hygiene commands afterwards.
- One attempt per scenario, no retries. Nothing was fixed during the run.

| Scenario | Result |
|---|---|
| 1. Lifecycle per agent | FAIL: 0 of 4 tasks reached `report_ready` |
| 2. Four-agent discussion | FAIL: stuck at round 1, rerouted to a non-participant, history rewritten on close |
| 3. Failure paths | FAIL: 6 of 7 checks pass; `delegate` of a `todo` task is not refused |
| 4. Auto-mode on a `todo` task | PASS, limited: no pickup in 20 min, consistent with the documented 2h rule, which was not exercised |
| 5. Hygiene, status, recall, insights | FAIL: inconsistent counts, divergent state not flagged |

## A. Dispatch routing ignores the requested agent

### F-01 (critical): the orchestrator overrides the contract owner and `--to`

```
shux agent enqueue -p . --to opencode --task t-oc-01 --json
shux agent enqueue -p . --to pi --task t-pi-01 --json
```
Launcher log for the opencode task:
```
Orchestrator routing for t-oc-01:
  Owner:    codex-cli
Launching Codex (delegate-to-codex.sh)...
```
The pi task was routed to codex-cli the same way, and a claude-code task was also routed to codex-cli. Expected: the owner and `--to` are honoured (enqueue has a separate `--force-reassign` for changing the target). Actual: an LLM orchestrator picks another agent, with no warning and no ledger entry, and the launcher log file keeps the requested agent's name.

### F-02 (high): `delegate --no-orchestrate` still runs the orchestrator

```
SUPERHARNESS_CONFIRM_NON_INTERACTIVE=YES shux delegate --task t-oc-01 --to opencode --no-orchestrate --non-interactive </dev/null
```
```
Orchestrator routing for t-oc-01:
  Owner:    claude-code
Launching Claude (delegate-to-claude.sh)...
```
`--help` says "Skip orchestrator, dispatch directly without analysis". The same happened with `--to codex-cli --no-orchestrate`.

### F-12 (medium): `shux delegate <id>` launches interactively instead of enqueuing, and fails without a record

`shux delegate t-codex-01 </dev/null` prints `Error: stdin is not a terminal`, then `Launching Codex (delegate-to-codex.sh)...`, and exits 1. The contract is unchanged and no ledger entry is written. The project instructions describe `shux delegate <id>` as create-and-enqueue; the enqueue path is actually `shux agent enqueue`.

### F-13 (medium): `delegate` of a `todo` task is not refused, while `enqueue` is

- `shux delegate --task t-fp-close --to codex-cli --no-orchestrate --non-interactive` on a `todo` task: `Note: auto-applying --plan-only ... agent will propose a plan.`, then a launch, exit 1, no ledger entry.
- `shux agent enqueue -p . --to codex-cli --task t-fp-todo --json`: `"error": "blocked: task 't-fp-todo' has status 'todo' which is not dispatchable for workflow 'implementation'."`

The two entry points apply different gates.

### F-25 (low): the two entry points accept different target lists

`shux delegate --to nosuch-agent` lists `claude-code, codex-cli, gemini-cli, opencode, pi, prime-agent`; `shux agent enqueue --to nosuch-agent` lists the same without `prime-agent`. Both correctly refuse the unknown agent.

## B. Codex model id and failure classification

### F-03 (high): codex-cli is launched with a provider-prefixed model id that Codex rejects

`shux agent enqueue -p . --to codex-cli --task t-codex-01`:
```
model: openai/gpt-5.6-luna
ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error","message":"The 'openai/gpt-5.6-luna' model is not supported when using Codex with a ChatGPT account."}}
```
Cause (read, not traced at runtime): `harnesses/base.py` `build_generic_invocation` calls `apply_model_prefix(model)` for codex-cli, and `utils/model_routing.py` returns `openai/<model>` for any `gpt-` id. That prefix is meant for OpenCode; Codex takes a bare id. Every codex-cli launch in the run failed: 4 task dispatches and 6 discussion launches.
Assumption, unverified: the bare `gpt-5.6-luna` may also be refused on a ChatGPT-authenticated Codex account.

### F-04 (medium): the failure is misclassified and blamed on the wrong agent

- Diagnostic: `reason=auth_mismatch: codex model not supported on current ChatGPT account`.
- `shux context t-oc-01`: `opencode — dispatch_failed`; `shux insights` attributes the same failure to opencode and pi.

Expected: attributed to codex-cli, the agent that actually ran, and classified as an invalid model id. The auth classification points the operator at the wrong fix.

## C. Lifecycle does not record results

### F-05 (critical): claude-code's committed work is orphaned and the dispatch is marked failed with no reason

`shux agent enqueue -p . --to claude-code --task t-cc-01 --json`, daemon running:
- Agent log: `Done. Both criteria pass: subtract(5,3)=2, test_subtract PASSED. Commit: c1bbff5.`
- `shux status`: `plan_approved  t-cc-01  claude-code  (35m)  [claude-code:failed]`; `shux insights` shows an empty reason.
- The dispatch worktree is emptied (only `.superharness` remains) and removed from `git worktree list`; `git branch -a --contains c1bbff5` returns nothing.

The work is reachable only by SHA until `git gc`. The task stays `plan_approved`, with no handoff and no ledger line.
Assumption: marked failed because the agent wrote no handoff or status; the code path was not traced.

### F-06 (high): dispatch never moves a task out of `plan_approved`

A run that produced a handoff with `status: report_ready` left the contract at `plan_approved`, so:
```
shux close --id t-oc-01 --actor owner --summary "divide implemented"
Cannot close task 't-oc-01': status is 'plan_approved', expected report_ready or review_passed.
```
During every launch `shux status` showed `plan_approved ... [<agent>:launched]`, never `in_progress`. The dispatch prompt tells the agent to "use `shux contract` to update task status", but `shux contract` cannot change status.

### F-14 (medium): failure reasons appear only in the daemon log

A task created with `--timeout-minutes 1` and moved to `in_progress` was auto-failed correctly (`lifecycle: task t-fp-deadline2 deadline exceeded (1m >= 1m) → failed`). But `shux context` shows no reason, `shux recall deadline` shows the task with date `unknown` and no reason, and the ledger has no line for it. F-05 has the same gap.

### F-19 (low): `shux hygiene` passes on divergent state

`Contract hygiene check passed.` while a handoff said `report_ready` and the contract said `plan_approved`, and three dispatches had failed.

### F-22 (low): `verify` is accepted on a `plan_approved` task

`shux verify --id t-oc-01 --result pass ...` returns `Verified task 't-oc-01': PASS` before any report; `close` then refuses on status.

## D. Discussion

### F-07 (high): a discussion stalls at round 1 when one participant fails

```
shux agent discuss start --topic "should sandboxpkg validate inputs with exceptions or return codes?" --owners codex-cli,opencode,pi,claude-code --max-rounds 3
```
Nine minutes later: `No consensus at round 1` (pi partial, opencode partial, claude-code agree, codex-cli failing per F-03), and `discussions: active=1 ... failed_participant=0`. The daemon escalated the round with `reason: all_owners_exhausted (tried: claude-code, codex-cli, gemini-cli, opencode, pi)`, although three of those had already submitted. Round 2 never started.

### F-08 (high): auto-recover reroutes a discussion round to a non-participant

`auto-recover: re-routed 'discuss-.../round-1' codex-cli → gemini-cli (recovery_1/2)`. Gemini was not in `--owners` and received the project prompt anyway.

### F-09 (medium): a successful pi submission is recorded as a permanent failure

pi's verdict landed (`pi: verdict=partial`), yet its run is recorded as `reason=permanent_block: command or file not found` after `Pi protocol error: event 'agent_settled' followed agent_end`, and `shux insights` shows `retries=3` for a single launch.

### F-10 (high): `discuss close` rewrites failed participants as `done`

`shux agent discuss close -p . --id <id>` returned `"cancelled_inbox_items": 3`. Inbox counts went from `done=2 failed=6` to `done=5 failed=3`, and every participant row became `:done`, including the three that had failed. The round task stayed `waiting_input` and its worktree remained.

### F-11 (medium): re-enqueue loop and retry budget not enforced

The daemon log shows `Enqueued round 1 for codex-cli` 52 times in eight minutes, and `retry budget exhausted` followed later by `attempt 1/3` again. Six codex-cli round-1 launches exist against a budget of 3.
Assumption: most of the 52 lines were de-duplicated no-ops; not checked in SQLite.

### F-23 (low): discussion UX gaps

`shux agent discuss status <id>` prints `No pending user approvals.` (the approval-gate status, not the discussion). `discuss summary` lists only the participants who submitted and does not say that one never did or that the round was stuck.

## E. Diagnostics and operations

### F-15 (medium): doctor and enqueue contradict the running daemon, and doctor passes a 0/4 model check

`shux doctor`: `WARN watcher:... not loaded` and `PASS models:0/4 adapters have a working model`; `shux agent enqueue`: `watcher not loaded`. At the same moment `shux daemon status` reported the daemon running, `shux status` reported `watcher: level=ok`, and the daemon did dispatch the item.

### F-16 (low): the daemon restarts the watcher every ~5s and logs it as an error

`daemon: watcher exited cleanly (rc=0), restarting in 5s` repeats every ~5s in `.superharness/watcher-errors.log` (11,440 bytes in 13 minutes), while `shux daemon status` reports `interval: 30s`.

### F-17 (medium): `shux init` creates no `profile.yaml`, and doctor does not flag it

`shux ops pipeline-check` fails with `missing profile.yaml`, the daemon logs `self-diagnosis: MISSING: profile.yaml` every cycle, and `shux doctor` reports no failure. `pipeline-check` also checks four agent binaries but not `pi`.

### F-18 (medium): insights and status disagree

`shux insights`: `failed 24, success rate 0%`; `shux status`: `done=2 failed=6` at the same moment.
Assumption: insights may count every retry and discussion attempt; its denominator is not documented.

### F-24 (low): dispatch worktrees are reused stale and never cleaned

A worktree from an earlier attempt (age 12m) was reused. After the run, five directories under the dispatch worktree root still hold only `.superharness`, while `git worktree list` lists none. The shared root also holds leftovers from other projects.

## F. Privacy and authority

### F-20 (medium, privacy): unrelated personal vault notes are injected into every dispatch prompt

Every launcher log contains a `Vault notes relevant to this task (via obsidian-semantic)` block quoting a personal job-search note, plus a machine-wide `Global Learning (from all projects on this machine)` block. These prompts go to third-party model providers for a sandbox task. Expected: project-scoped context, with cross-project personal notes opt-in.

### F-21 (low): `--actor` is self-asserted

`shux task status --id t-fp-review --status review_failed --actor codex-cli` succeeds when run by anyone claiming the owner's name, while `--actor owner` is refused (`forbidden: actor 'owner' cannot update task ... owned by 'codex-cli'`). The requested lifecycle checks themselves passed: `todo -> done` is rejected, the `review_failed -> plan_proposed` loop works, and `in_progress -> stopped` works.

## Not tested

- Gemini, except the involuntary launch in F-08.
- A second attempt per agent, for example forcing a bare Codex model id.
- The real opencode and pi task adapters: every task attempt was rerouted (F-01, F-02). Both were exercised only inside the discussion.
- `verify` then `close` on an agent-completed task: blocked by F-06; `--force` was not used.
- The auto-mode `todo` 2h rule: observed for 20 minutes only.
- How a provider rate limit surfaces: none occurred.
- SQLite contents: counts come from CLI output only.

## Suggested fix order

1. F-01, F-02, F-03: without them no task reaches opencode, pi or codex-cli. F-01 and F-02 likely share the orchestrator entry in `delegate`.
2. F-05, F-06: results must reach the contract and the branch.
3. F-10, F-07, F-08: discussion state must stay truthful.
4. F-20: stop sending personal notes to providers by default.
5. The rest, as one diagnostics pass.
