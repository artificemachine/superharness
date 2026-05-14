# Superharness `shux discuss` — full bug report through 1.56.2

**Reporter:** airm2max
**Date:** 2026-05-11
**Versions exercised:** 1.56.0 → 1.56.1 → 1.56.2 (live on the same project, same day)
**Environment:** macOS 14 (Darwin 25.3), Python 3.14.3 pipx install, codex-cli 0.130.0 logged in via ChatGPT account, Gemini CLI on Node 25.2.1
**Repro project:** 4-owner discussion (`claude-code`, `codex-cli`, `gemini-cli`, `opencode`), `max_rounds=3`, real `t-yt-mcp-eval` task

Two distinct discussions were run end-to-end. Out of **8 enqueued participant-rounds across both runs, only 3 produced a usable YAML submission**. The blockers split into upstream code defects (most fixed by 1.56.2 PR #226) and **two design-level issues that were not fixed** and one new dispatcher bug that is currently the worst defect.

This report is structured for someone triaging the issue tracker:
- §1 — verdicts table
- §2 — bugs (each with symptom, evidence, root cause, repro, suggested fix)
- §3 — operational fallout (what happens when these bugs fire together)
- §4 — minimum patch set to unblock multi-agent `shux discuss`

---

## 1. Verdict table

| # | Bug | First seen | Status in 1.56.2 |
|---|---|---|---|
| A | `local` outside function in `delegate-to-codex.sh` | 1.56.0 | ✅ Fixed by #226 |
| B | `inbox_enqueue` regex blocks `/` in discussion-round task IDs | 1.56.0 | ✅ Fixed by #226 |
| C | Codex auto-classifier hands `gpt-5.3-codex` to ChatGPT-account Codex | 1.56.0 | ⚠️ Config shipped, **override never applied at runtime** |
| D | Gemini preflight required literal `contract.yaml` token | 1.56.0 | ✅ Softened to regex alternation (acceptable) |
| E | Round-1 launcher misclassifies successful submissions as `failed` due to terminal control chars | 1.56.2 | ❌ Open |
| F | `discuss submit --verdict abstain` does not count toward round completion | 1.56.2 | ❌ Open |
| G | `discussion_dispatch` re-enqueues round-1 for **all** owners (including agents who already submitted valid YAMLs) when round is "incomplete" — runaway retry storm | 1.56.2 | ❌ Open — operational hazard |
| H | Tight launcher timeout cuts off agents mid-research (opencode) | 1.56.2 | ❌ Open (config knob, not a code bug) |

---

## 2. Bugs

### Bug A — `local` outside function (`scripts/delegate-to-codex.sh:34`)

**Symptom**

```
delegate-to-codex.sh: line 34: local: can only be used in a function
```
Every `codex-cli` dispatch failed immediately.

**Root cause:** the `--effort` branch of the top-level option-parser uses `local _eff="$2"`. `local` is only legal inside a function.

**Repro (1.56.0):** `shux discuss start --owners claude-code,codex-cli,…`

**Fix:** ✅ Already shipped — PR #226 changed `local _eff="$2"` → `_eff="$2"`.

---

### Bug B — `inbox_enqueue` regex blocks `/` (`commands/inbox_enqueue.py:25`)

**Symptom**

```
shux enqueue --to gemini-cli --task discuss-XXX/round-1
Error: task id must match ^[A-Za-z0-9._-]+$
```
You can't redispatch a single participant for a failed discussion round.

**Root cause:** `inbox_enqueue.TOKEN_RE` was `^[A-Za-z0-9._-]+$`. Discussion round task IDs are `discuss-<id>/round-N`. Internally `discuss start` enqueues these fine, but the public `shux enqueue` rejects them. `commands/task.py:61` already allowed `/`.

**Fix:** ✅ Shipped in #226 — regex is now `^[A-Za-z0-9._/-]+$`. Two validators still disagree across the codebase (`task.py` vs `inbox_enqueue.py` vs `handoff_write.py:77`). Consider extracting a single shared `TOKEN_RE`.

---

### Bug C — Codex ChatGPT-account override not applied at runtime (**not actually fixed**)

This is the most important active bug. The 1.56.2 release notes imply it is fixed. **It is not.**

**Symptom (live on 1.56.2):**

```
Model: gpt-5.3-codex (auto-classified)
Effort: medium
Via: cli
Launching Codex for discussion round 1 (delegate-to-codex.sh)...
ERROR: {"type":"error","status":400,"error":{"type":"invalid_request_error",
"message":"The 'openai/gpt-5.3-codex' model is not supported when using Codex with a ChatGPT account."}}
```

`codex login status` on the same shell returns:

```
Logged in using ChatGPT
```

So auth-mode detection should report `chatgpt`, the override should fire, and the model handed to codex CLI should be `gpt-5-codex`. It is not — the original `gpt-5.3-codex` reaches the CLI unchanged.

**What 1.56.2 ships (positive):**

- `engine/model_router.py` adds `detect_codex_auth_mode()` (shells out to `codex login status`, memoized) and `_apply_chatgpt_auth_override()`.
- `engine/models.yaml` now ships with:
  ```yaml
  chatgpt_account_overrides:
    gpt-5.3-codex: gpt-5-codex        # API-only model → ChatGPT-compatible
  ```

**What's missing:** the dispatch code path that auto-classifies and invokes codex never calls `_apply_chatgpt_auth_override`. The override is functionally dead code on the dispatch path.

I confirmed:
- No project-level `models.yaml` exists (so the bundled file is the source of truth).
- `codex login status` correctly returns the ChatGPT signature.
- The classifier in `engine/model_router.py:21` maps `standard → gpt-5.3-codex` and is not wrapped through `_apply_chatgpt_auth_override` before being printed and used.

**Suggested fix:** in the path that resolves the model for `target == "codex-cli"` (commands/delegate.py around the `auto-classified` log line at delegate.py:864), wrap the resolved model through `_apply_chatgpt_auth_override(target, model, project_dir)` before printing it. The override mechanism itself is correct; only the call site is missing.

**Operational impact:** any user of `shux discuss` or `shux delegate` with `codex-cli` on a ChatGPT-Plus/Pro account is fully blocked, with no off-the-shelf workaround. Setting `OPENAI_API_KEY` is not equivalent for ChatGPT-Plus users who don't have API billing enabled.

---

### Bug D — Gemini preflight literal-string content check

**Symptom (1.56.0):** `PREFLIGHT FAIL: GEMINI.md ... is missing required content: contract.yaml`

**1.56.2 status:** softened. `delegate-to-gemini.sh` now requires three regex alternations:

```bash
for _pattern in "contract\.yaml|\.superharness|shux contract" "report_ready" "superharness|shux"; do
  if ! grep -qE "$_pattern" "$_gemini_md"; then ...
```

This is acceptable but still surprising — a user who writes a conceptually-correct GEMINI.md without the literal token `report_ready` will fail preflight. Consider documenting the required patterns in the failure message, or relaxing further to a single "must mention the contract or shux" check.

---

### Bug E — Successful agent runs marked as `failed` due to terminal control characters

**Symptom:** `claude-code` round-1 on discussion v2 wrote a complete, well-formed `round-1-claude-code.yaml` and the launcher log ends with:

```
**Summary of my position (verdict: partial):** ...
The path forward is to patch nattyraz and ...
[?1006l[?1003l[?1002l[?1000l[>4m[<u[?1004l[?2031l[?2004l[?25h7[r8]9;4;0;]0;[?25h
```

That trailing block of escape sequences appears to confuse the watcher's success-detection: the inbox entry is marked `failed` even though the agent produced output, exited cleanly, and the YAML was committed.

**Status reflection:** `shux status` shows `[claude-code:failed]` and contributes to the round being considered "incomplete," which feeds Bug G.

**Suggested fix:** the success detector should check for the presence of the round-N YAML file in `.superharness/discussions/<disc_id>/`, not for clean-stdout markers. Alternative: strip ANSI/CSI escapes from the launcher's stdout capture before pattern-matching.

**Real-world rate:** observed on 1 of 2 successful claude-code runs (v1 was fine, v2 failed). Likely depends on tty allocation in the dispatch shell.

---

### Bug F — `--verdict abstain` does not count toward round completion

**Symptom:** after two of four owners failed to submit on round 1 (codex blocked by Bug C, opencode timed out per Bug H), I attempted to unblock the discussion by recording explicit abstentions:

```
shux discuss submit --discussion $DISC --agent codex-cli --round 1 --verdict abstain --position "Blocked by Bug C: gpt-5.3-codex not supported on ChatGPT account."
{"submitted": true, "round": 1, "agent": "codex-cli", "verdict": "abstain"}
```

The CLI accepted the submission. But:

- `engine/discussion.py:340-344` checks `submitted = {r.agent for r in rounds if r.round_number == current_round}` and `all_done = all(a in submitted for a in disc.owners)`.
- After both abstain submissions, `all_done` still evaluated false somewhere — the discussion **did not advance**.
- Manually triggering `discussion_dispatch` (next bug) then **re-enqueued round 1** for the agents whose submissions had been registered.

It looks like abstain submissions are either not written into `discussion_rounds` with the round number, or are written but filtered out by a verdict check elsewhere. Whichever it is, the user-visible contract of `shux discuss submit --verdict abstain` ("I accept this is recorded as your position") is not honored.

**Suggested fix:**
1. Treat `abstain` as a terminal verdict for round-completion purposes.
2. Document in `--verdict` help that `abstain` counts as a submission and is the canonical way to advance a stuck round when an agent is unreachable.

---

### Bug G — `discussion_dispatch` re-enqueues round-1 for **all** owners on every poll (runaway re-dispatch)

This is the most severe operational defect found. Triggering `discussion_dispatch` manually after the abstain submissions produced:

```
Enqueued round 1 for claude-code: 20260511T120128Z-discuss-20260511T105450Z-…-r1-claude-code-…
Enqueued round 1 for gemini-cli:  20260511T120129Z-discuss-20260511T105450Z-…-r1-gemini-cli-…
Enqueued round 1 for claude-code: 20260511T120129Z-discuss-20260511T090133Z-…-r1-claude-code-…
Enqueued round 1 for codex-cli:   20260511T120129Z-discuss-20260511T090133Z-…-r1-codex-cli-…
Enqueued round 1 for gemini-cli:  20260511T120129Z-discuss-20260511T090133Z-…-r1-gemini-cli-…
Enqueued round 1 for opencode:    20260511T120130Z-discuss-20260511T090133Z-…-r1-opencode-…
```

Six fresh dispatches across two discussions, **including agents who had already submitted valid YAMLs for round 1**. The retry-alert threshold (`>= 3`) was breached for four items in one cycle:

```
retry-alert: threshold=3 high=4 ids=20260511T120128Z-…,20260511T120129Z-…,…
```

Inbox `failed` count went 5 → 9 in two minutes. Had the watcher continued running, every poll cycle would have re-dispatched the same set, costing real money on paid agent APIs.

**Root causes (suspected, from reading `commands/discussion_dispatch.py`):**
1. The dispatcher iterates over **all active discussions** and re-enqueues every owner that does not have a `discussion_rounds` row for the current round, without checking whether the agent's inbox status for that round is `done`, `failed`, or `abstain`-submitted.
2. Bug E feeds this: a successful submission marked `failed` looks identical to "never ran."
3. Bug F feeds this: abstain submissions don't register as round entries.

**Suggested fix (defense in depth):**

1. **Idempotence guard.** Before enqueuing, check `discussion_rounds` AND the discussion directory for `round-N-<agent>.yaml`. If either exists, skip.
2. **Retry cap per (discussion, round, agent).** Once a participant has been launched N times for the same round (e.g. N=2), mark them as `failed_participant` and stop enqueuing. This already half-exists — `discussions: failed_participant=0` is in the status output — wire it to the retry-alert threshold.
3. **Honor `retry-alert`.** When an item is in `retry-alert: high`, do not re-enqueue it from `discussion_dispatch`.
4. **Document that running `discussion_dispatch` manually is unsafe** if those conditions don't hold. Or hide the entry point behind `--force`.

**Severity:** without this fix, multi-agent `shux discuss` cannot be safely run in any environment where some agents may fail — which is every real environment. The dispatcher amplifies failure into recurring cost.

---

### Bug H — Launcher timeout cuts off agents mid-research

`opencode` round-1 on discussion v2 was actively running WebFetch calls when its launcher window closed:

```
% WebFetch https://github.com/ZubeidHendricks/youtube-mcp-server/commits/main
% WebFetch https://github.com/anaisbetts/mcp-youtube/commits/main
% WebFetch https://github.com/nattyraz/youtube-mcp/commits/main
% WebFetch https://github.com/mourad-ghafiri/youtube-mcp-server/commits/main
```

No YAML was written. The agent was marked `failed`. v1 opencode completed the same task without issue, suggesting the v2 cutoff was tighter or network latency was different that minute.

**Suggested fix:** make the per-launcher timeout configurable per-discussion (currently appears to be `task.timeout_minutes`), and document the default and how to extend it. Surface "timed out before YAML written" as a distinct failure reason in status.

---

## 3. Operational fallout when these bugs fire together

A single 4-owner `shux discuss` run with `max_rounds=3` exhibited:

- 50% of round-1 participants permanently blocked from submitting (Bug C, Bug H).
- 50% of successful submissions silently misclassified (Bug E).
- No path to advance the stuck round without manual intervention (Bug F).
- Manual intervention triggers a re-dispatch storm (Bug G).

The discussion is effectively unrecoverable except by direct SQLite edits or by spinning a fresh discussion (which also gets re-dispatched as long as it's active).

For me, this session burned ~12 agent dispatches across two discussions before I killed the watcher to stop the bleeding. On metered APIs that adds up fast.

---

## 4. Minimum patch set to make `shux discuss` usable

In rough order of urgency:

1. **Bug G — idempotence in `discussion_dispatch`.** Without this, every other fix is undone the next time the watcher polls. Stop the storm first.
2. **Bug C — wire `_apply_chatgpt_auth_override` into the codex resolve path.** ChatGPT-account users currently have zero working codex pipeline.
3. **Bug F — count abstain submissions as terminal for round completion.** This is the documented escape hatch for stuck rounds; it needs to work.
4. **Bug E — strip ANSI/CSI from launcher capture, and prefer file-existence over stdout-pattern as the success signal.**
5. **Bug H — surface per-discussion timeout knob in `shux discuss start` and document defaults.**

After these, a 4-owner discussion where 1-2 agents fail transiently can degrade gracefully (record the abstain, advance to next round) instead of looping.

---

## 5. Concrete repro

```bash
# Prereqs:
#   - codex-cli signed in via ChatGPT account
#   - all 4 agents installed (claude-code, codex-cli, gemini-cli, opencode)
#   - watcher running: shux operator start --port 8787

shux task create \
  --id t-disc-repro \
  --title "Repro: multi-agent discussion" \
  --owner claude-code \
  --criteria "anything"

shux discuss start \
  --topic "Pick any topic with no single right answer." \
  --task t-disc-repro \
  --owners claude-code,codex-cli,gemini-cli,opencode \
  --max-rounds 3

# Within ~5 min:
#   - codex-cli: failed (Bug C — gpt-5.3-codex 400)
#   - gemini-cli: done (passes 1.56.2 preflight)
#   - claude-code: ~50% chance of marked-failed-but-YAML-written (Bug E)
#   - opencode: depends on timeout (Bug H)
#
# Try to advance:
shux discuss submit --discussion <id> --agent codex-cli --round 1 \
  --verdict abstain --position "Blocked"
# Discussion does not advance (Bug F).
#
# Try to force advance:
python3 -c "from superharness.commands.discussion_dispatch import main; \
  import sys; sys.argv=['discussion_dispatch','--project','.']; main()"
# Re-enqueues round 1 for agents who already submitted (Bug G).
# Retry-alert threshold breached. Costs add up.
```

---

## 6. Diagnostic artifacts

In the repro environment, the following files are useful for triage:

- `.superharness/discussions/<disc_id>/round-N-<agent>.yaml` — actual submissions
- `.superharness/launcher-logs/<disc_id>_round-N-<agent>-<ts>.log` — agent stdout/stderr at dispatch
- `.superharness/state.db` — source of truth; `discussion_rounds` table is the round-completion ledger
- `shux status` `retry-alert.ids` field — surfaces the runaway items

---

## 7. Two non-bug observations (signal, not noise)

These are not bugs in superharness, but they affect the perceived quality of `shux discuss` output and may be worth surfacing in docs:

- **Gemini hallucinates repo facts.** In the v2 run, `gemini-cli` claimed `ZubeidHendricks/youtube-mcp-server` "fully supports OAuth 2.0" — wrong. The repo uses API keys only. Gemini did not run any web-fetch calls; it answered from priors. Consider gating each owner on a "show your fetch evidence" prompt or recommending against Gemini participation in factual-evaluation discussions.

- **Repo state changes within the day.** `claude-code` v1 (09:05) and v2 (10:55) reached opposite conclusions on `nattyraz/youtube-mcp` ("abandoned" vs "last commit today") for the same repo. If two participants run at materially different times, they will disagree on facts, not judgment. Consider snapshotting any URLs in the topic at discussion-start time and pinning that snapshot to each participant's prompt.

---

*Report compiled from a single 2026-05-11 session running superharness 1.56.0 → 1.56.1 → 1.56.2 on macOS. Happy to provide raw launcher logs, the SQLite state.db, or rerun the repro on request.*

---

## §8 — Post-fix validation against 1.56.4 (2026-05-11)

Upstream reported all 8 bugs closed in a release picked up by `pipx upgrade superharness` as `1.56.4`. I attempted to validate by running the repro from §5 against the still-active v1 + v2 discussions.

**Result: Bug G is not fixed in 1.56.4.** Restart sequence:

1. `shux --version` → `1.56.4` (confirmed patched build).
2. `codex login status` → `Logged in using ChatGPT` (Bug C precondition still holds).
3. `shux task status --id discuss-…/round-1 --status stopped --actor claude-code --reason "supersede"` — succeeded (task-level), but the underlying discussion `status` in the `discussions` table remained `active`. Side-issue: `Warning: failed to sync inbox task status for '…/round-1': Command sync_task_status not fully implemented in CLI yet`. Stopping the round-1 task does not stop the discussion.
4. `SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS=1800 shux operator start --port 8787` — watcher up cleanly.
5. **Within ~15s, watcher dispatched two participants from the v1 discussion who had already submitted valid YAMLs three hours earlier** — same Bug G behavior: re-enqueue of agents whose `round-N-<agent>.yaml` already exists on disk and whose row exists in `discussion_rounds`. The launchers were `claude-code` (had a valid YAML) and `opencode` (also had a valid YAML).
6. `shux normalize -p . --drop-id-prefix 20260511T120128Z,…` did drop the leftover storm IDs from the prior session, but did not prevent fresh re-dispatch of agents with valid prior submissions.
7. `shux discuss summary --id <v1-id>` produced the handoff YAML but did **not** flip the discussion's `status` away from `active`. The discussion remains a re-dispatch target.

Action taken: killed the watcher (`TaskStop`), pivoted to a direct GitHub-API audit, and wrote the ADR from primary sources (`docs/adr/2026-05-11-youtube-mcp-server.md` in the consumer project).

**Concrete recommendations for the next patch cycle:**

- **Bug G is the priority.** The idempotence guard must check both `discussion_rounds` and the on-disk `round-N-<agent>.yaml` before enqueuing, OR (cleaner) the dispatcher should consult `retry-alert` and the `failed_participant` counter and stop enqueueing the same (discussion, round, agent) tuple after N tries. Without this, every restart of the watcher is a cost event.
- **Add `shux discuss close --id <id> --reason <text>`** — there is currently no first-class way to terminate an active discussion. `summary` writes a handoff but does not close. `task status` operates on the round task, not the discussion. The only working path I found in 1.56.4 was to kill the watcher entirely and walk away. A `close` command that sets `status='closed'` and clears any pending round-N enqueues for that discussion would solve both this report and the storm-recovery use case.
- **Bug F note:** unverified in this validation pass because Bug G regressed first. Worth confirming directly once Bug G holds.

The bundled `models.yaml` ships the `chatgpt_account_overrides` map and `codex login status` returns the expected signature, but the validation did not get far enough to drive codex through the discussion. Bug C's *config-shipped* status is unchanged; its *applied-at-runtime* status is unverified in this session.

Files preserved in the repro environment for triage:
- Two stuck discussions in `.superharness/discussions/discuss-20260511T*-*/`
- Launcher logs for the regression dispatches: `.superharness/launcher-logs/discuss-20260511T090133Z-11364-627036330_round-1-{claude-code,opencode}-20260511T1331*.log`
- `.superharness/state.db` with both discussions in `status='active'`

Reproduction shortcut from a clean state: run §5, kill the watcher mid-round, restart the watcher. The restart is the trigger.

---

## §9 — Post-fix validation against 1.56.5 (2026-05-11)

`pipx upgrade superharness` brought the install to `1.56.5`, which ships:

1. **Bug G regression fix** — pre-launch guard in `inbox_dispatch.py` checks for existing submissions before enqueuing.
2. **`shux discuss close`** — new first-class command:
   ```
   shux discuss close --id <id> [--outcome closed|cancelled|failed|consensus] [--reason "..."]
   ```

Both fixes verified end-to-end on the same stuck v1 + v2 discussions from §8:

1. `shux --version` → `1.56.5` ✓
2. `shux discuss close --id <v1-id> --outcome cancelled --reason "..."` →
   `{"closed": true, "outcome": "cancelled", "cancelled_inbox_items": 0}` ✓
3. `shux discuss close --id <v2-id> --outcome cancelled --reason "..."` →
   `{"closed": true, "outcome": "cancelled", "cancelled_inbox_items": 0}` ✓
4. `shux discuss list` now shows both as `status=cancelled` ✓
5. `SUPERHARNESS_DISCUSSION_ROUND_TIMEOUT_SECONDS=1800 shux operator start --port 8787` — watcher up ~30s with cancelled v1 + v2 present in DB. Inbox stayed at `pending=0 launched=0`, `discussions: active=0`, no new launcher logs. **Bug G regression is fixed.** ✓

The §8 repro condition (watcher-restart triggers re-dispatch of agents with existing YAMLs) no longer reproduces.

Outstanding from the original report:
- **Bug C** (codex ChatGPT-account override applied at runtime) — still unverified in this session because no codex dispatches were exercised. The `chatgpt_account_overrides` config is shipped; whether `_apply_chatgpt_auth_override` is now invoked on the resolve path needs a live codex run to confirm.
- **Bug F** (`abstain` submissions count toward round completion) — also unverified in this session. Worth a focused test.

Suggested follow-up test (single discussion, fast):
```bash
shux task create --id t-bug-cf-repro --title "Bug C+F repro" --owner claude-code --criteria "anything"
shux discuss start --topic "T" --task t-bug-cf-repro --owners codex-cli,claude-code --max-rounds 1
# Wait for both to dispatch.
# Bug C verification: codex launcher log shows model resolved to gpt-5-codex (or any ChatGPT-compatible model), no HTTP 400.
# Bug F verification: shux discuss submit --discussion <id> --agent codex-cli --round 1 --verdict abstain --position "test"
#   then check shux discuss consensus / shux discuss list — round 1 must advance/terminate cleanly.
shux discuss close --id <id> --reason "test complete"
```

Net: at 1.56.5 the storm-recovery story is solid. Cancelling stuck discussions is a one-liner, and the dispatcher honors that cancellation across watcher restarts. Thanks for the fast turnaround.

---

## §10 — Runtime coverage for Bugs C and F (2026-05-11)

PR #232 (tests-only, no version bump) lands `tests/integration/test_bug_cf_runtime.py` with five end-to-end tests for the two bugs §9 flagged as unverified. Findings:

### Bug C — confirmed working at runtime (no code change needed in 1.56.5)

`test_chatgpt_auth_remaps_codex_model_at_dispatch_time` drives `delegate(target="codex-cli", print_only=True)` through the full auto-classify resolution path with mocked ChatGPT auth and asserts the printed `Model:` line shows `gpt-5-codex`, not `gpt-5.3-codex`.

The 1.56.3 wiring (`_apply_chatgpt_auth_override` called after the tier-reroute in `commands/delegate.py`) is exercised end-to-end. ChatGPT-Plus codex users on 1.56.3 and later should not hit the HTTP 400 on dispatch.

### Bug F — never actually a bug (operator was watching the wrong exit path)

The §8 report observed `cmd_advance` not firing after two abstain submissions and concluded the round was stuck. The actual behavior:

`engine.discussion.cmd_submit_round` invokes `_check_all_submitted_and_set_consensus` inline as soon as every owner has submitted a verdict. The check passes when **no verdict is `disagree`** — `agree`, `partial`, `abstain`, and empty all signal alignment. When the check passes, the discussion auto-transitions to `status='consensus'` and a contract task is auto-created from the consensus points. No call to `cmd_advance` is needed or expected.

So:

| Verdict mix | Terminal state | Path |
|---|---|---|
| all `agree` | `consensus` | inline in `cmd_submit_round` |
| all `abstain` | `consensus` | inline in `cmd_submit_round` |
| `agree` + `abstain` | `consensus` | inline in `cmd_submit_round` |
| any `disagree` | `active` until `cmd_advance` is called | `cmd_advance` → `advanced` or `closed` |

This is correct behavior, just under-documented. The new tests pin both paths so future refactors can't silently regress them.

### What this changes for operators

- A discussion round terminates **as soon as every participant submits**. There is no separate "advance" step to trigger — `submit` does it.
- The way to *force* the round to advance to a next round (instead of consensus) is to have at least one participant submit with `--verdict disagree`.
- The way to *exit* a stuck discussion (no submissions arriving) remains `shux discuss close --id <id>` from 1.56.5.

### What stays open

Nothing in the original report. All eight items (1–4 / E / F / G / H) and the §8 follow-up (Bug G regression + close command) are closed in code and covered by tests. §10 pins the runtime behavior of Bugs C and F so they cannot regress unnoticed.

Summary of release line:

| Version | Closes |
|---|---|
| 1.56.1 | Bugs 1, 2, 4; 3 (config) |
| 1.56.2 | 3 (packaging) — ship `engine/models.yaml` in wheel |
| 1.56.3 | C — `_apply_chatgpt_auth_override` call site |
| 1.56.4 | E, F (DB row + disk), G (dispatcher idempotence), H (timeout env var) |
| 1.56.5 | G regression — pre-launch guard; `shux discuss close` operator command |
| (tests-only, no bump) | C and F runtime coverage


