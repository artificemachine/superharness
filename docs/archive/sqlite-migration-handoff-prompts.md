# SQLite Migration — Direct Handoff Prompts

> **Purpose:** self-contained prompts to paste into each agent's session so
> work can begin without using the superharness watcher/dispatcher loop.
>
> Each prompt is designed to be copy-pasted verbatim. All context the agent
> needs is either inline or referenced as a repo file path.

## Coordination Model

```
┌─────────────────────────────────────────────────────────────────┐
│              Branch: feat/sqlite-ledger-migration               │
└─────────────────────────────────────────────────────────────────┘

Iter 1 — Schema           → Gemini 3 (Auto)
Iter 2 — Migration bridge → Gemini 3
Iter 3 — DAOs             → Gemini 3
  ║
  ║ GATE 1 — Opus 4.7 max review (schema + DAO correctness)
  ║
Iter 4 — Dual-write       → Claude Sonnet 4.6
Iter 5 — Parity           → Claude Sonnet 4.6
  ║
  ║ GATE 2 — Opus 4.7 max review (parity + 24h soak)
  ║
Iter 6 — CLI port         → Claude Sonnet 4.6
Iter 7 — Stress + rollback → Claude Sonnet 4.6
  ║
  ║ GATE 3 — Opus 4.7 max review (cutover readiness)
  ║
Iter 8 — Read cutover     → Claude Sonnet 4.6
Iter 9 — Dashboard        → Gemini 3
Iter 10 — YAML archival   → Claude Sonnet 4.6
Iter 11 — phi4-mini del   → Claude Sonnet 4.6
  ║
  ║ FINAL SHIP REVIEW — Opus 4.7 max
  ║
  ▼
merge to main
```

All work lands on the single branch `feat/sqlite-ledger-migration`.
No shux dispatch. No watcher involvement. Direct implementation only.

---

## 1. Gemini 3 — Iterations 1-3 (schema, migration, DAOs)

Paste this into a Gemini 3 session with the repo as the working directory.

````
Implement iterations 1, 2, and 3 of the SQLite ledger migration for superharness.

Repo: <project-root>
Branch: feat/sqlite-ledger-migration (already created from main — use it, do not create a new one)

READ FIRST, in this order, before any code:
1. docs/plans/sqlite-ledger-migration.md — the full plan (Architecture, Schema, Iterations 1-3)
2. docs/specs/state-backend-interfaces.md — the interface contract. Every public signature you write must match this exactly.
3. docs/plans/sqlite-migration-tasks.yaml — your three task entries:
   - sqlite-1-schema
   - sqlite-2-migration
   - sqlite-3-daos
   Each has acceptance criteria and TDD blocks you must satisfy.

Scope (STRICT):
- Iteration 1 — DB init + WAL + versioning framework (sqlite-1-schema)
- Iteration 2 — Migration bridge (sqlite-2-migration)
- Iteration 3 — DAOs + atomic claim + watcher singleton (sqlite-3-daos)

Discipline per iteration:
- RED: write failing tests first (tests/unit/db/test_*.py)
- GREEN: implement to make tests pass
- REFACTOR: clean up
- One commit per iteration in conventional format: feat(engine): <message>

Hard rules:
- Do NOT touch src/superharness/commands/inbox_watch.py, inbox_dispatch.py, dashboard-ui.py, or anything under src/superharness/harness/. Those belong to later iterations owned by another agent.
- Do NOT implement dual-write, parity monitoring, or CLI changes.
- Only add modules inside src/superharness/engine/ and tests inside tests/unit/db/.
- No new runtime dependencies beyond stdlib sqlite3.
- All public function signatures must exactly match docs/specs/state-backend-interfaces.md. If a signature in the spec seems wrong, STOP and flag it — do not silently deviate.
- mypy --strict must pass on every new module.
- Do NOT commit to main. All commits go on feat/sqlite-ledger-migration.

STOP condition:
After iteration 3 tests pass and you have three commits pushed, STOP. Do not start iteration 4. A human will run the review gate (sqlite-review-1-schema-dao) in Claude Opus 4.7 max mode before unblocking further work.

Deliverable:
- Three commits on feat/sqlite-ledger-migration
- Open a PR titled: "feat(engine): SQLite state backend — iterations 1-3 (schema, migration, DAOs)"
- Write a report handoff to .superharness/handoffs/sqlite-3-daos-report-<YYYYMMDDTHHMMSS>-gemini-cli.yaml summarizing:
  - Modules created and their purpose
  - Key design decisions
  - Any deviations from the spec and why
  - Test counts (pass/fail/skip)
  - What the reviewer should double-check
````

---

## 2. Claude Sonnet 4.6 — Iterations 4, 5, 6, 7, 8, 10, 11

Start this session ONLY after Gemini's iterations 1-3 are done AND
`sqlite-review-1-schema-dao` has passed (clean Opus max review).

Paste this into a fresh Claude Code session on Sonnet 4.6.

````
Continue the SQLite ledger migration for superharness. You are implementing iterations 4, 5, 6, 7, 8, 10, and 11 (iteration 9 belongs to Gemini).

Repo: <project-root>
Branch: feat/sqlite-ledger-migration (Gemini's iter 1-3 must already be committed here and the review gate must have passed)

READ FIRST, in this order:
1. docs/plans/sqlite-ledger-migration.md
2. docs/specs/state-backend-interfaces.md
3. docs/plans/sqlite-migration-tasks.yaml — your task entries:
   - sqlite-4-dualwrite
   - sqlite-5-parity
   - sqlite-6-cli-port
   - sqlite-7-stress-rollback
   - sqlite-8-read-cutover
   - sqlite-10-yaml-archival
   - sqlite-11-phi4-disposition
4. src/superharness/engine/ — Gemini's work (db, inbox_dao, tasks_dao, handoffs_dao, failures_dao, decisions_dao, ledger_dao, review_dao, watcher_singleton, migrate_yaml). Do NOT modify these signatures.
5. src/superharness/commands/inbox_watch.py and inbox_dispatch.py (current YAML paths you are adding dual-write to)
6. src/superharness/harness/ (the phi4-mini layer you will delete in iter 11)
7. The review handoff at .superharness/handoffs/sqlite-review-1-*.yaml (any concerns raised must be addressed or acknowledged)

Order of work (do not skip):
- Iteration 4 — Dual-write wiring (watcher + dispatcher)
- Iteration 5 — Parity monitoring
- [HARD STOP] push, open review handoff at .superharness/handoffs/sqlite-5-parity-report-<ts>-claude-code.yaml, wait for sqlite-review-2-parity to pass
- 24h soak on the superharness repo itself — parity must stay at 0 for 24 consecutive hours
- Iteration 6 — CLI command porting (full audit, not partial)
- Iteration 7 — Stress test + rollback rehearsal + backup/restore commands
- [HARD STOP] push, wait for sqlite-review-3-cutover-ready to pass
- Iteration 8 — Read-path cutover
- 7-day soak on the superharness repo itself (can overlap with Gemini's iter 9)
- Iteration 9 belongs to Gemini — coordinate or skip
- Iteration 10 — YAML archival + external compat + shux export yaml command
- Iteration 11 — phi4-mini deletion + harness layer repurpose
- [HARD STOP] push, request sqlite-ship-review

Discipline per iteration:
- RED → GREEN → REFACTOR
- One commit per iteration, conventional format
- Handoff written to .superharness/handoffs/<iter-id>-report-<ts>-claude-code.yaml after each iteration
- Mark iteration [DONE] in docs/plans/sqlite-ledger-migration.md as you complete each

Hard rules:
- Do NOT commit to main. Always on feat/sqlite-ledger-migration.
- Do NOT skip the three review gates. Opus 4.7 max must review and approve each gate before you proceed.
- Do NOT delete anything from src/superharness/harness/ before iteration 11.
- Do NOT change the schema or DAO signatures from iter 1-3. If you find a bug, stop and flag it — do not silently patch.
- STATE_BACKEND=yaml_only must remain a working rollback path through iteration 9.
- Dual-write transaction boundary is strict: SQLite write + yaml_sync_queue enqueue MUST commit in the same transaction, or neither.
- No YAML writes outside the yaml_sync.py drain worker after iteration 4.
- Never use --no-verify, --no-gpg-sign, or any hook-bypass flag on commits.

Deliverable format:
- One long-lived PR on feat/sqlite-ledger-migration, updated iteration by iteration (easier review than three separate PRs)
- PR title: "feat(engine): SQLite ledger migration — iterations 4-11"
- Final commit before ship review bumps version to 2.0.0 (breaking change due to YAML archival)
- CHANGELOG.md append-only, one line per completed iteration
- At ship-review time, the PR must include a 14-day soak evidence log from the superharness repo itself showing parity stayed at 0
````

---

## 3. Opus 4.7 max — Review Gate Prompts

Run each review in a fresh Claude Code session. Switch to Opus + max before
the review begins.

### Gate 1 — Schema + DAO Review (after Gemini's iter 1-3)

````
/model claude-opus-4-7
/effort max

Review sqlite-review-1-schema-dao for the SQLite ledger migration.

Context:
- Branch: feat/sqlite-ledger-migration
- Plan: docs/plans/sqlite-ledger-migration.md
- Spec: docs/specs/state-backend-interfaces.md
- Task entry with acceptance criteria: docs/plans/sqlite-migration-tasks.yaml (id: sqlite-review-1-schema-dao)

What to verify:
- Schema matches the Schema section of docs/plans/sqlite-ledger-migration.md exactly (table names, column types, indexes, constraints)
- Every public DAO function signature matches docs/specs/state-backend-interfaces.md exactly (names, parameter order, keyword-only markers, return types)
- blocked_by is implemented as the task_dependencies many-to-many table, NOT as a TEXT column
- handoffs table is row-per-event (append-only), preserves history across multiple plan→report→review cycles
- tasks.version optimistic concurrency is enforced — stale updates raise ConcurrencyError
- Atomic claim uses UPDATE...WHERE...RETURNING in a single statement, not SELECT-then-UPDATE
- watcher_singleton supports stale takeover (new PID can claim if incumbent heartbeat is stale)
- JSON-encoded fields decode back to correct Python types in dataclasses
- No sqlite3.Error leaks to callers — all wrapped as StateError subclasses
- init_db() is idempotent — running twice produces identical schema
- SQLite version check rejects <3.35 with ConnectionError
- Tests include multi-threaded concurrency scenarios for claim_next

Deliverable:
Write the review handoff to .superharness/handoffs/sqlite-review-1-schema-dao-<YYYYMMDDTHHMMSS>-claude-code.yaml with:
- Verdict: approved | needs_fixes
- Per-criterion: pass/fail
- Findings: specific file:line references
- Recommended action for each failure

If approved, iteration 4 is unblocked. If not approved, Gemini takes the findings and revises iterations 1-3.
````

### Gate 2 — Parity System Review (after Sonnet's iter 4-5 + 24h soak)

````
/model claude-opus-4-7
/effort max

Review sqlite-review-2-parity for the SQLite ledger migration.

Context:
- Branch: feat/sqlite-ledger-migration
- Plan: docs/plans/sqlite-ledger-migration.md
- Task entry: docs/plans/sqlite-migration-tasks.yaml (id: sqlite-review-2-parity)
- 24h soak log: .superharness/handoffs/sqlite-5-parity-soak-*.yaml

What to verify:
- Parity detects every drift class: missing rows in SQLite, missing rows in YAML, mismatched fields, orphaned foreign keys, extra rows in either backend
- heal_parity is idempotent — calling twice on the same drift does not duplicate sync ops
- heal_parity is safe during active writes (uses transactions, not read-then-write races)
- yaml_sync_queue.drain() handles partial-failure retries without losing ops
- SQLite write + yaml_sync_queue.enqueue commit in the same transaction (both or neither)
- 24h soak log shows drift count stayed at 0 for the entire period
- shux doctor output accurately reflects drift counts and yaml_sync_queue lag under test drift injection
- Dual-write path is the only mutation path — no direct YAML writes outside yaml_sync.py

Deliverable:
Write the review handoff to .superharness/handoffs/sqlite-review-2-parity-<YYYYMMDDTHHMMSS>-claude-code.yaml.

If approved, iterations 6+ are unblocked. Silent parity bugs here become silent corruption at cutover (iter 8) — no margin for error.
````

### Gate 3 — Cutover Readiness Review (after iter 6-7 + 7-day soak)

````
/model claude-opus-4-7
/effort max

Review sqlite-review-3-cutover-ready for the SQLite ledger migration.

Context:
- Branch: feat/sqlite-ledger-migration
- Task entry: docs/plans/sqlite-migration-tasks.yaml (id: sqlite-review-3-cutover-ready)
- Stress test report: docs/benchmarks/sqlite-stress-*.md
- 7-day soak log in handoffs

What to verify:
- Stress test: 50 processes × 30 min × random ops → 0 corrupt rows, 0 deadlocks, acceptable p99 latencies
- Chaos test: SIGKILL during writes → WAL recovery restores last committed state
- Large dataset: 10k tasks, get_pending p99 < 100ms
- Cross-platform: tests passed on macOS AND Linux
- Rollback rehearsal actually tested both directions (dual → yaml_only → dual) with parity re-convergence verified
- Backup/restore commands work on a populated DB
- CLI audit (iter 6) is complete — every state-touching command verified in the matrix
- Every write command has a parity-asserting test
- Release notes draft is ready and covers YAML deprecation, shux export yaml usage, rollback plan
- 7-day soak on superharness repo itself shows 0 drift

Deliverable:
Write the review handoff to .superharness/handoffs/sqlite-review-3-cutover-ready-<YYYYMMDDTHHMMSS>-claude-code.yaml.

If approved, iteration 8 (read cutover) is unblocked. This is the last gate before reads flip to SQLite — after iter 8, rollback is possible but costly.
````

### Final Ship Review (after iter 11 complete)

````
/model claude-opus-4-7
/effort max

Run the final ship review for the SQLite ledger migration (sqlite-ship-review).

Context:
- Branch: feat/sqlite-ledger-migration
- Task entry: docs/plans/sqlite-migration-tasks.yaml (id: sqlite-ship-review)

What to verify:
- Version bumped to 2.0.0 (breaking change from YAML archival)
- CHANGELOG.md is append-only and complete — one line per completed iteration
- All iteration handoffs exist in .superharness/handoffs/
- Release notes at docs/release-notes/v2.0.0.md cover:
  - YAML archival breaking change
  - shux export yaml compat command for external scripts
  - Rollback procedure (post-archival requires restore from *.yaml.bak-<ts>)
  - phi4-mini Ollama dependency removal
- No dead phi4-mini code remains (grep for "OllamaHarnessClient", "WatcherHealthAdvisor", "phi4-mini")
- docs/plans/sqlite-ledger-migration.md marked [SHIPPED] with final commit SHA
- 14-day stability evidence from the superharness repo itself attached to the PR
- All tests pass (unit + integration + stress)
- mypy --strict passes

Additional due diligence:
- Run /ultrareview on the full branch for multi-agent validation
- Manually eyeball the deletion diff for iter 11 to confirm no accidentally-removed code

Deliverable:
Write the final ship review handoff to .superharness/handoffs/sqlite-ship-review-<YYYYMMDDTHHMMSS>-claude-code.yaml with a clear ship/no-ship verdict.

If approved, the PR is ready to merge to main.
````

---

## 4. Environment Notes

- **SQLite version:** `sqlite3 --version` must be ≥ 3.35 on the implementer's machine. macOS Sonoma ships 3.39+; Linux varies.
- **Python:** same version as the existing superharness project (3.11+).
- **Ollama:** not needed for this migration (we are removing the phi4-mini dependency, not adding it).
- **Git hooks:** global pre-commit hook validates changelog and entrypoints — honor them, never bypass.
- **Soak periods:** 24h after iter 5 and 7-day after iter 6 are NOT optional. Parity bugs compound. These gates exist because silent drift is the single highest risk of this migration.

---

## 5. When Things Go Wrong

**Review gate rejection:**
- Gemini/Sonnet re-reads the review handoff, addresses findings, pushes a fix commit, re-requests review.
- Do not proceed past a rejected gate under any circumstance.

**Schema change discovered mid-iteration:**
- STOP. Open an issue or escalate to a human.
- Amending the schema after iter 3 affects every downstream iteration.
- If the change is necessary: add a new migration in db.py (increment CURRENT_SCHEMA_VERSION), update the spec doc, update the plan, then continue.

**Parity drift during dual-write phase:**
- Investigate immediately. Do not start iter 6 if drift is non-zero.
- If parity cannot reach 0 within the 24h soak, re-open iter 4 or iter 5.

**Rollback invocation (post-cutover):**
- Set `STATE_BACKEND=yaml_only` across all processes.
- Run `shux doctor` to confirm YAML consistency.
- File an incident report — this means iter 8 shipped with a bug that the review gate missed.
