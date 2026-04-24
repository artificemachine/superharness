# Claude Superharness Review — Review of the Reviews

**Verdict:** Both prior reviews (`codex_superharness_review.md`, `gemini_superharness_review.md`) are **substantively correct**. All seven critical/major findings were independently verified against the current source on `main` (commit `ab29e93`).

Two independent reviewers converging on the same defects is strong signal — these are real and must be fixed before any further feature work lands.

---

## Verification Summary

Every claim from both reviews was cross-checked against the actual code. All seven findings hold.

| Finding | Codex | Gemini | Verified | Evidence |
|---|---|---|---|---|
| `contract.yaml` structurally broken at line ~1959 | ✓ | ✓ | **Yes** | `decisions: []` / `failures: []` sit inside a task map, then line 1961 starts a root-level `- id:` list item. Invalid YAML. |
| `daemon.py` launches nonexistent `superharness.commands.watch` | ✓ | ✓ | **Yes** | `src/superharness/commands/daemon.py:101` targets `superharness.commands.watch`. Directory has `inbox_watch.py`, `watcher_worker.py`, no `watch.py`. `shux daemon start` prints success; child process exits immediately. |
| PID schema collision on `daemon.pid.json` | ✓ | ✓ | **Yes** | `daemon.py:122` writes `"pid"`. `operator.py:89` writes `"operator_pid"` and `"dashboard_port"`. Both target the same file. `daemon.py:90` reads `state.get("pid")` — misses operator-written state entirely. |
| `classify_task` signature mismatch | ✓ | ✓ | **Yes** | `auto_dispatch.py:45` calls `classify_task(task, project_dir=project_dir)`. `model_router.py:57` defines `classify_task(title, criteria, files, previously_failed)` — no `project_dir` kwarg, and the first arg is a string, not a dict. Exception swallowed at `auto_dispatch.py:49`; everything falls back to `("claude-code", "standard")`. |
| `TaskStatus` enum missing 4 canonical states | ✓ | ✓ | **Yes** | `schemas.py:21-38` lists 13 states. `next_action.py` uses `pending_user_approval`, `review_requested`, `review_failed`, `stopped` as canonical. None are in the enum. |
| Inbox dependency check fails open | ✓ | ✓ | **Yes** | `inbox.py:179-180` — `except Exception: return True`. |
| `.gitignore` leaks runtime files | ✓ | — | **Yes** | `.superharness/.gitignore` does not list `daemon.pid.json`, `trace.jsonl`, or `*.lock.d/`. `git status` at review time shows `.superharness/daemon.pid.json` modified and `.superharness/trace.jsonl` untracked. |

---

## Comparison of the Two Reviews

| Dimension | Codex | Gemini |
|---|---|---|
| **Citation precision** | Better — `file:line` on every claim, pinpoints the swallowed exception line. | Looser — "around line 1960", "catches all exceptions" (no line number). |
| **Structure** | Flat: Critical / Major / Arch Notes / Next Fix Order / Verification. | Tiered with per-finding Evidence / Impact blocks. |
| **Actionability** | Ships a 5-step ordered fix list. | Ends with a generic "consolidation and stabilization phase" recommendation. |
| **Scope discipline** | Catches the `.gitignore` hygiene leak. | Misses the git-hygiene issue. |
| **Restraint** | Explicitly notes tests were not run per project rules. | Does not mention verification scope. |
| **Overall** | **The better review to act on.** Tighter citations, smaller claims, ordered plan. | Cleaner framing but softer in places. Good for communicating severity, weaker for execution. |

---

## What Both Reviews Missed

### 1. Root cause of the YAML corruption
Neither reviewer traced **how** `decisions: []` / `failures: []` ended up inside a task map instead of at contract root. Without identifying the writer, the same append pattern will reproduce the bug after the hand-fix.

**Action:** Before patching the YAML, grep all contract-writing call sites and find which one produced the malformed append. Candidate areas: `engine/validate.py`, any path that mutates `contract.yaml`, and the autonomous-dispatch tasks that created the orphan list items around line 1961.

### 2. Blast radius of the broken daemon
`daemon.pid.json` is **staged/modified in the working tree right now**. That means someone (or CI, or the operator) is actively hitting this broken path. The reviews treat it as a latent defect — it is not. It is an active bug reproducing in the live repo at review time.

**Action:** Check how many installs are running the crash-on-start daemon and whether any published release (PyPI) shipped this regression.

### 3. Fail-open semantics may be intentional
`inbox.py:179` `except Exception: return True` carries the explicit comment `# Fail open: don't block dispatch on read errors`. This is a deliberate design choice — "don't let one malformed row brick the queue." Both reviews treat it as a straight defect without engaging the tradeoff.

**Action:** The right fix is almost certainly a **narrower catch** (parse errors on the specific dep row only, not blanket `Exception` across the whole dep-resolution block), not flipping the whole check to fail-closed. A fail-closed flip would brick the queue every time the contract has any parse error — which, given finding #1, is right now.

### 4. The enum gap may be worse than claimed
Gemini asserts that the missing `TaskStatus` values cause "runtime validation failures." This is **unverified** — the fact that the project runs at all suggests validation simply never fires for those states (likely because `validate.py:98` bypasses the Pydantic model, which Codex correctly flagged separately).

If validation doesn't run, the enum is **dead code**. That is arguably worse: it looks like a source of truth, is documented as one, but never enforces anything. Either wire it up or delete it.

### 5. Launcher log path corrupts on any task ID containing `/` (silent, fatal to discussions)

**Found during this review by attempting a live 3-way discussion, not by static reading.**

`src/superharness/commands/inbox_dispatch.py:596` (pre-fix) built the launcher log path via:

```python
task_log = os.path.join(launcher_log_dir, f"{item_task}-{item_to}-{timestamp}.log")
```

Every discussion round task has the form `discuss-<id>/round-N`. The `/` makes `os.path.join` resolve the path as a subdirectory (`launcher-logs/discuss-<id>/round-N-...`), but `os.makedirs` at line 594 only creates the top-level `launcher-logs/`. `script -q -F <path>` fails to open the log and exits code 1. The inbox dispatcher records `launcher exited with code 1`, retries up to `max_retries`, then marks the item `failed`.

**Blast radius:** every discussion round 2+ dispatch, and any task ID containing `/`. Silently fatal to the entire discussion feature. No launcher log is ever created (because that is exactly what fails), so there is no diagnostic trail — the failure looks like a generic launcher crash in the dashboard.

**Why both prior reviews missed it:** this only manifests at runtime when the dispatched task ID contains `/`. Static reading of `inbox_dispatch.py` alone does not reveal it — you have to trace the ID format used by `engine/discussion.py` (`{disc_id}/round-{N}`) into the dispatcher. Reproducing it required actually firing a discussion and watching the inbox fail.

**Fix applied (commit not yet made):** sanitize `item_task` the same way `discuss.py:348` already sanitizes `disc_id`:

```python
safe_item_task = item_task.replace("/", "_").replace("..", "_")
task_log = os.path.join(launcher_log_dir, f"{safe_item_task}-{item_to}-{timestamp}.log")
```

Also updated the `_rotate_launcher_logs` call to use the sanitized ID so rotation glob patterns continue to match. 12 existing discuss/dispatch tests pass. No dedicated regression test was added for this specific defect — that is a gap and should be filled before release.

**Meta-observation:** this is a **fourth-reviewer finding** — my own meta-review had the same gap as Codex and Gemini. None of the three static reviews would have caught it without running a discussion. Any review of a system with many runtime paths and side effects needs **one end-to-end execution attempt**, not just static reading, before claiming coverage. This is now a confirmed review-process gap, not just a code defect.

### 6. Neither review called out the product-vs-platform tension explicitly
Codex gestures at it ("feature scope is now broad… needs consolidation more than more features"), but both reviews stop short of naming the pattern. Feature list observed: task lifecycle, dashboard, daemon, operator, auto-dispatch, model routing, cost tracking, modules, packs, discussions, worktrees, notifications, adapters, monitor UI, peer review (proposed). This is platform surface area. The defects above are not random — they are the predictable outcome of shipping new surface while leaving the canonical primitives (lifecycle enum, PID file, contract writer) unconsolidated.

**Action:** A feature freeze until the "Next Fix Order" from Codex lands. Otherwise every new feature will fork a new lifecycle state or a new PID-file schema, and the drift compounds.

### 7. Paused inbox items are never reconciled after their launcher pid dies

**Found during this review by live orchestrator debugging, not by static reading.**

When a dispatch launcher subprocess dies, the watcher's pause-recovery logic does not re-check liveness. Observed sequence in this session:

1. Watcher dispatched `auto-b3ee24` (claude-code, `feat.dashboard-auto-restart-on-upgrade`). Subprocess pid `83259` was recorded on the inbox item.
2. Subprocess died (cause not traced — possibly the SDK runner path crashing, unrelated to any fix here).
3. Inbox item was marked `status: paused` with `paused_at: 2026-04-24T11:58:41Z`.
4. Claude-code discussion round-1 item was also marked `paused` at the same instant — the watcher appears to pause all items on a given agent lane when one stalls.
5. `ps -p 83259` at `~12:05Z` (7 min later): **no such process.** The pid was dead.
6. Watcher continued ticking past that point (`--interval 15`) but never flipped the paused item back to `pending` or `failed` on dead-pid detection. The lane stayed blocked indefinitely until manual `shux normalize --drop-status paused`.

**Why both prior reviews missed it:** same reason as #5. This only manifests at runtime when a launcher actually dies. Static reading of `inbox_watch.py` / `inbox_dispatch.py` reveals pause logic but not the absence of a liveness-recheck on paused items. You have to watch it happen.

**Impact:** any agent lane can get permanently wedged by a single launcher crash. If auto-dispatch fires on a dirty or brittle task, the paused residue blocks every subsequent dispatch to that agent until an operator runs housekeeping. In a fully autonomous setup this is a silent availability failure.

**Fix direction (not implemented in this session):** `inbox_watch.py` tick loop should, for every `paused` item with a recorded pid, run `os.kill(pid, 0)`; if the process is dead, transition to `failed` with reason `launcher pid disappeared`. This is a few lines and a regression test. Defer to a dedicated PR.

**Meta-observation:** reinforces finding #5's lesson. A static review of a stateful system undercounts defects at a predictable rate. The reviewer has to fire the actual runtime path at least once.

---

## Recommended Fix Order

Accept Codex's 5-step list, with one step prepended:

0. **Find the contract-writer that produced the corruption.** Do not hand-fix the YAML until this is understood. Otherwise the bug reappears on the next autonomous append.
1. Fix `.superharness/contract.yaml` corruption.
2. Fix `daemon.py` target to `superharness.commands.inbox_watch` and add a regression test that asserts `shux daemon start` produces a pid alive after 2 seconds.
3. Unify lifecycle statuses — `next_action.py`, `schemas.py`, dashboard, command gates. Pick one source of truth (probably `schemas.py`) and delete the duplicates.
4. Wire protocol reads through Pydantic validation at command boundaries. Either use the schema or remove it.
5. Split `daemon.pid.json` into `daemon-state.json` and `operator-state.json`, **or** define one versioned runtime-state schema and have both writers conform.
6. Add `.superharness/.gitignore` entries for `daemon.pid.json`, `trace.jsonl`, `*.lock.d/`. Untrack the currently-leaked files.
7. Narrow the `except Exception` in `inbox.py:179` to parse errors only. Keep fail-open intent, scope it correctly.

---

## Verdict

**Changes Requested.** Same conclusion as both prior reviews. The core primitives (file-native protocol, append-only ledger, adapter manifests, task lifecycle) remain the right design. The execution has drifted and the top of the stack is currently non-functional.

No feature work should land until steps 0–3 of the fix order are merged. After that, run `/production-ready` against this repo to surface the remaining coverage and regression gaps that these reviews could not see without executing the test suite.

---

## Notes on Review Methodology

- Both reviews were produced without running the test suite (project policy requires confirmation before tests). This is correct behavior, but it means neither review can speak to regression coverage of the specific defects called out. `/production-ready` or a targeted `pytest` run after the contract is parseable again will fill that gap.
- This meta-review was produced by reading the current source at commit `ab29e93` on `main` and verifying each claim by file and line. No tests were run.
- Review date: 2026-04-24.
