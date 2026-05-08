# Handoff — superharness

> Latest: 2026-05-08 PM — planning-only session for portable-paths cleanup
> Previous: 2026-05-07 — branch `feat/test-unification-task`, uncommitted changes
> PyPI latest: v1.47.5

---

## 2026-05-08 PM session: Portable-paths cleanup planning

### What was added

Two planning docs in `docs/`. **No code changes to superharness in this session**
(a `fix/session-stop-no-mcp-kill` branch was created and immediately reverted
once the user pointed out that the upstream pkill block should not be silently
patched in their dev source tree).

| File | Purpose |
|------|---------|
| `docs/PLAN-portable-adapter-paths.md` | Per-project context: superharness needs a `superharness adapter-path <host> <hook>` CLI subcommand so external configs can resolve hook paths without hardcoding repo locations. Acceptance test included. |
| `docs/PLAN-portable-paths-cleanup.md` | Master TDD plan for the cross-repo cleanup. 4 phases: (1) superharness CLI, (2) obsidian-semantic-mcp launcher, (3) voice-toolkit docs, (4) agent-config migration. Phases 1-3 are independent; phase 4 depends on 1-3. |

### Why this matters

Agent configs (`~/.claude/settings.json`, `~/.claude.json`, `~/.opencode.json`,
`~/.pi/agent/mcp.json`) hardcode absolute paths to this repo's adapter hook
scripts. The same problem affects three projects. This session diagnosed the
root cause and wrote the cross-cutting plan but did NOT execute on superharness.

Specifically, `~/.claude/settings.json` lines 209/245/277/287/308 reference
`bash /Users/airm2max/DevOpsSec/superharness/src/superharness/adapters/claude-code/hooks/<hook>.sh`
which breaks under (a) repo moves, (b) release installs (`pip install
superharness`), (c) temp worktrees (a stale worktree path was already found and
fixed in `settings.json` earlier this session).

### What other projects shipped this session (for context)

- **voice-toolkit** — `chore/portable-mcp-config` branch (uncommitted): `_find_binary()` resolution order fixed (PATH-installed > source-relative). 5 new tests pass.
- **obsidian-semantic-mcp** — `chore/portable-mcp-config` branch (uncommitted): stdin reader rewritten to use `anyio.to_thread.run_sync(readline)`, fixing the 30s pipe-stdin hang that broke MCP over `docker exec`. 7 new tests. Image rebuild still pending.

### What the next session should do (superharness-specific)

1. **Phase 1 — implement `superharness adapter-path` CLI** per
   `docs/PLAN-portable-adapter-paths.md`. RED test, GREEN minimal impl
   using `importlib.resources`, REFACTOR to consume manifests from
   `adapter_manifests/*.yaml`.
2. **Phase 4 (after phase 1 ships)** — migrate `~/.claude/settings.json`
   to call `bash $(superharness adapter-path claude-code <hook>)` instead
   of hardcoded paths. The Stop hook is currently routed through
   `~/.claude/hooks/superharness-stop-no-mcp-kill.sh` (a local wrapper
   that strips the MCP-kill block from `session-stop.sh`); that wrapper
   should also be updated to use `superharness adapter-path` once
   phase 1 ships.
3. **Consider an upstream fix** to `session-stop.sh`: drop the trailing
   `pkill -TERM -f` block entirely. Claude Code already cleans up stdio
   MCP children on CLI exit, and the Stop event fires per-turn (not at
   session end), so pkill-ing here breaks long-lived MCP connections
   between turns. If accepted upstream, the local wrapper can be deleted.

### Cross-cutting follow-ups (not superharness's responsibility)

- Rebuild & publish obsidian-semantic-mcp image (owner-driven).
- Re-register voice-toolkit in `~/.opencode.json` to overwrite the stale
  absolute path now that `_find_binary()` resolves correctly.

---

## 2026-05-07 session: Watcher bug fixes

Three watcher bug fixes + regression test suites. All changes are on `feat/test-unification-task`, not yet committed.

### Fix 1 — Flood prevention: `auto_enqueue_approved()` in `inbox_watch.py`

Root cause of the 53-item flood bug: `auto_enqueue_approved()` only blocked re-enqueue of **active** (pending/launched/running) items. When dispatch failed, the item left the active set and the next watcher tick created a fresh item at `retry_count=0`, looping forever.

Three sub-fixes:
- **`failed_counts` guard**: COUNT failed items per task from SQLite; skip re-enqueue when `failed_counts[task_id] >= max_retries`
- **`StateError` catch**: wrapped `inbox_dao.enqueue` in `try/except` to swallow race-condition duplicates gracefully
- **YAML sync fix**: appended `new_items` (SQLite-only) not already in `current_items` back to YAML — fixed 2 pre-existing test failures in `test_auto_dispatch.py`

4 regression tests: `tests/unit/test_auto_enqueue_flood_prevention.py`

### Fix 2 — Zombie max-age cap: `_reconcile_zombies()` in `inbox_watch.py`

Root cause of the 406-minute stale launched item: alive-PID non-plan-only items had no wall-clock cap — the reconciler just `continue`d past them forever.

Added **Check 2c**: non-plan-only launched items with alive PIDs running > 2 hours get SIGTERM'd and marked failed. Plan-only items keep the existing 15-min cap (Check 2b). Updated docstring to list all 5 checks.

4 regression tests: `tests/unit/test_reconcile_zombie_max_age.py`

### Fix 3 — Auto-archive handoff filter: `_auto_archive_stale_tasks()` in `inbox_watch.py`

Root cause of stale `in_progress` tasks not being archived: the handoff check used `if handoffs: continue` — any handoff file, including a plan-phase one, blocked auto-archive. A task with a plan handoff from a failed gemini dispatch would sit `in_progress` indefinitely.

Fix: only `-report-` or `-done-` filenames exempt a task. Plan handoffs (`-plan-`) are ignored for the archive decision.

5 regression tests: `tests/unit/test_auto_archive_stale_tasks.py`

## Files changed (not yet committed)

- `src/superharness/commands/inbox_watch.py` — 3 fixes above
- `tests/unit/test_auto_enqueue_flood_prevention.py` — new (4 tests)
- `tests/unit/test_reconcile_zombie_max_age.py` — new (4 tests)
- `tests/unit/test_auto_archive_stale_tasks.py` — new (5 tests)

## First thing next session

Commit and PR all 3 fixes as a single patch:

```bash
git add src/superharness/commands/inbox_watch.py \
        tests/unit/test_auto_enqueue_flood_prevention.py \
        tests/unit/test_reconcile_zombie_max_age.py \
        tests/unit/test_auto_archive_stale_tasks.py \
        CHANGELOG.md HANDOFF.md
git commit -m "fix(watcher): flood prevention, zombie max-age cap, auto-archive handoff filter (vX.Y.Z)"
gh pr create ...
```

Bump version (patch: fix commit) in `pyproject.toml` + `CHANGELOG.md` before committing.

Also: PR #190 (`fix/auto-dispatch-valid-agents-v1.47.5`) may still be open — check `gh pr list` and merge first if so.

## Tasks completed this session (report_ready — awaiting shux close)

- `feat.dashboard-auto-restart-on-upgrade` — report_ready (implementation verified, 8/8 tests GREEN)
- `feat.refactor-do-dispatch-decomposition` — report_ready (decomposition was already done, dead stubs removed, 11 tests added)

## Known remaining issues

- Pre-existing CI failures on unit/integration/E2E (same failures on `main`) — `test_enqueue_writes_inbox` is the main one (SQLite-only mode doesn't write `inbox.yaml`). Tracked separately.
- Watcher lock hash differs between Python environments (pyenv 3.11 vs pipx/homebrew 3.14) — each computes a different hash for the same project path, so two instances can both think they hold the lock. Fix: normalize to `os.path.realpath()` in `watcher_lock_path()`.
- `_classify_task()` in `auto_dispatch.py` still has a hardcoded `mini→codex-cli / else→claude-code` tier mapping — needs model router awareness of all 4 agents. Low urgency.

## Previous roadmap items (deferred)

- **PR #2-B**: split-brain test fixtures (`test_task_workflow_v2_phase1.py`, `test_task_failed_reason.py`)
- **PR #2-C**: reconciler bugs (`_reconcile_zombies` never defined, `zombie_reconcile.py` missing)
- **PR #3-B**: ancillary commands YAML→SQLite (`onboard.py`, `inbox_watch.py`, `handoff_write.py`, `recap.py`, `preflight.py`, `recall.py`)
