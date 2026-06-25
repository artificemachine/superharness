# superharness — next session handoff

**date:** 2026-04-12
**from:** owner + claude-code (morpheme session)
**to:** claude-code / codex-cli

---

## current contract state

| status | count |
|--------|-------|
| done | ~45 tasks |
| todo | 1 (`feat.task-lifecycle-ship`) |
| report_ready | 1 (`feat.morpheme-phase1-smoke`) |

### open items

- **`feat.task-lifecycle-ship`** — auto-commit after task approval
  blocked by: review pipeline bypass risk (pre-commit hook conflict)
  decision needed: safe path to `git commit` post-close without bypassing hooks

- **`feat.morpheme-phase1-smoke`** — smoke task for morpheme integration
  status: `report_ready` — needs owner verification + `shux close`

---

## architecture snapshot (2026-04-12)

### what works today
- full task lifecycle: `todo → plan_proposed → plan_approved → in_progress → report_ready → done`
- model routing: haiku auto-classifies tasks → tier (mini/standard/max) → maps to actual model
  - claude-code: haiku / sonnet / opus
  - codex-cli: gpt tiers
- sub-task decomposition: `shux delegate --orchestrate` → opus breaks task into subtasks
  - **gap:** only works for `claude-code`, not `codex-cli`
- inbox dispatch: atomic claim + launch, flock-based mutex, stale timeout 300s
- adapter-payload v1.0: stable json boundary to morpheme
- modules: 12 loaded (obsidian, ntfy, telegram, ship, openclaw, doctor, security, etc.)
- worktree gc, inbox gc, watcher auto-gc all operational

### known gaps
- `model:` field in `ContractTask` uses `extra="allow"` — not formally declared in schema
- `openclaw_send_task()` stub — waiting on SSH relay to claw-relay (site A network)
- live log streaming: PTY buffering on macOS drops lines under load
- zombie reconciler: race condition on `inbox.yaml` under concurrent dispatch
- windows: `SIGALRM` missing — affects timeout handling
- daemon mode: not yet implemented

---

## proposed roadmap (decided this session)

### phase 1 — schema & routing hardening
priority: high | effort: low

- declare `model: Optional[str]` formally in `ContractTask` (schemas.py ~line 86)
- extend `--orchestrate` decomposition to `codex-cli`
- add cross-agent decomposition: opus splits a task across multiple agents
- validate `effort:` values at `shux init` / `shux contract`

**why now:** model routing is already built and used in production — schema gap is a silent failure risk.

### phase 2 — live agent feedback loop
priority: medium | effort: medium

- heartbeat protocol: agent writes `.superharness/heartbeat.yaml` every n minutes
- new status: `paused` / `waiting-input` — agent signals human required
- expose heartbeat in `adapter-payload` → morpheme shows "last seen x min ago" on nodes

**why:** currently there is no visibility into a running agent between dispatch and handoff.
a long-running task looks identical to a stale/zombie task.

### phase 3 — intelligent dispatch
priority: high | effort: high

- `shux auto-dispatch` — scans all `todo` tasks, classifies each, routes to best agent+model
- opus-level decomposition gate: tasks above effort threshold auto-decomposed before dispatch
- budget guard: refuse dispatch if estimated cost exceeds project budget in profile.yaml
- multi-agent split: single task split with parts routed to claude-code AND codex-cli in parallel

**why:** this is the core value proposition — the system should route work, not the operator.

### phase 4 — reliability & recovery
priority: medium | effort: medium

- fix zombie reconciler race on `inbox.yaml` (concurrent dispatch edge case)
- fix PTY buffering on macOS for live log streaming
- `shux recover --dry-run` before mutating inbox state
- windows SIGALRM replacement

### phase 5 — external bridges
priority: low | effort: high

- complete `openclaw_send_task()` → SSH relay to claw-relay
- telegram / discord approval flow for `waiting-input` tasks
- cron parser for scheduled dispatch
- `shux discuss` thread summaries → written back to handoffs

---

## morpheme integration notes

morpheme consumes `shux adapter-payload --json` (schema v1.0).

**what morpheme currently visualizes:**
- task graph with dependency edges
- statuses, owners, costs
- ledger, failures, decisions, inbox tabs
- edge labels (contract / blocked by / parent hidden)

**what morpheme would gain from each roadmap phase:**

| phase | morpheme gain |
|-------|--------------|
| 1 | model tier badge on each node (mini / standard / max) |
| 2 | heartbeat pulse on in_progress nodes, `waiting` status colour |
| 3 | decomposition tree — parent task expands to sub-task children |
| 4 | no more stale/zombie nodes appearing on canvas |
| 5 | inbox shows relay/bridge destination per task |

**adapter-payload must stay at schema_version 1.0** — any breaking change requires
bumping the version and updating morpheme's adapter.js simultaneously.

---

## decisions made this session

| decision | reason |
|----------|--------|
| morpheme font: plus jakarta sans everywhere | replaced inter + jetbrains mono for visual consistency |
| morpheme urls: `/projects`, `/projects/:name`, `/get-started`, `/demo` | clean routing, each view has own url |
| demo nodes: auth-service workflow | replaced fictional brand nodes with realistic multi-agent task chain |
| roadmap priority: phase 1 before phase 3 | schema gaps are silent failures — fix foundation before building routing |

---

## start next session with

```bash
cd <path/to/superharness>

# check current state
shux contract
shux status

# verify the smoke task
shux recall "morpheme phase1"

# close the smoke task if verified
shux close feat.morpheme-phase1-smoke

# begin phase 1
# 1. open schemas.py and add model: Optional[str] = None to ContractTask
# 2. run tests: npm test / pytest
# 3. shux delegate feat.task-lifecycle-ship (the one open todo)
```

---

## context for feat.task-lifecycle-ship (the blocked todo)

the task wants to auto-commit after `shux close` completes.
the risk: pre-commit hook blocks commits on `main` and runs shipguard.
if the agent auto-commits on the wrong branch or without running checks, it bypasses the review pipeline.

**proposed safe path:**
- only auto-commit on a feature branch (check current branch before committing)
- run `.project-hooks/pre-commit` explicitly before `git commit`
- if hook fails → write failure to handoff, do not commit, notify owner
- gate behind `ship_on_close: true` in `profile.yaml` (opt-in, not default)
