# Session Handoff — 2026-04-07

**From:** claude-code
**To:** owner / next session
**Branch:** main
**Version:** 1.15.1 (shipped to PyPI)

---

## What Was Done

### 1. Task Workflow v2 Phase 1 (PR #89)
- `ContractTask` schema: added `effort`, `out_of_scope`, `definition_of_done`, `context`, `timeout_minutes`, `progress_timeout_minutes`
- `Contract` schema: `default_definition_of_done` for project-level DoD inheritance
- `tdd` field aliased to `plan` (backward compatible)
- `development_method` no longer restricted — accepts any string
- `task create` CLI: 9 new flags (`--effort`, `--test-types`, `--out-of-scope`, `--definition-of-done`, `--context`, `--timeout-minutes`, `--bdd-given/when/then`)
- 20 new tests, 1635 total passing

### 2. Inbox GC + Watcher Auto-GC (PR #89, #90)
- `shux inbox-gc` command: reconciles stale inbox items (stopped/failed/paused/stale) against contract
- GC covers tasks past dispatch phase (report_ready, review_requested, etc.), not just done
- Watcher runs GC every N cycles (default 5, configurable via `profile.yaml gc_interval_cycles`)
- Writes ledger entry for each reconciled item

### 3. Dispatch Improvements (PR #90)
- **Worktree isolation**: dirty worktree → temp git worktree created, agent runs in clean checkout, main untouched
- **failed_reason** recorded on inbox items when dispatch fails
- **Reason fields cleared** on forward inbox transitions (pending/launched/running)
- **SUPERHARNESS_CONFIRM_NON_INTERACTIVE** set automatically in spawn_env
- Falls back to pause if worktree creation fails

### 4. Dashboard UX (PR #89, #90, #91, #92, #93)
- **HTML extracted** to separate `dashboard.html` — eliminates Python string escaping bugs
- **Reason column** in inbox table with clickable details panel
- **Cancel Review** / **Approve Without Review** buttons for review_requested tasks
- **Reviewer picker** dropdown (claude-code / codex-cli)
- **Unified queue flow**: not queued (clickable) → queued (pill) → re-queue
- **Activity feed**: live timeline of dispatch, gc, inbox events
- **Git context**: branch, dirty count, last commit in header
- **Task dependency graph**: press `g` to toggle mermaid diagram
- **Keyboard shortcuts**: `r` refresh, `g` graph, `l` list, `b` board, `?` help
- **Dispatch preview**: model, effort, cost, timeout in enqueue modal
- **Desktop notifications**: native macOS alert on task done/failed
- **var(--fg) → var(--text)** fix for CSS variable consistency

### 5. New CLI Commands
- `shux worktree-gc` — clean orphaned dispatch worktrees
- `shux recap [--hours N]` — session timeline (ledger, inbox, handoffs, task changes)
- `shux notify-desktop` — native macOS/Linux desktop notification

### 6. Status Fix (PR #90)
- `shux status` recognizes foreground watchers via heartbeat — shows `level=ok foreground` instead of `level=bad not loaded`

### 7. Global Rules Updated
- Rule 6: branch guard on direct commits — never `ALLOW_MAIN_COMMIT=1` without explicit request
- Rule 13: before PR verify version bump + CHANGELOG; after merge verify tag + release + publish
- `/ship` command: mandatory gate after merge (steps 16-17 cannot be skipped); auto mode detects project state

---

## PRs Shipped

| PR | Title | Version |
|----|-------|---------|
| #89 | feat: task workflow v2 phase 1 + inbox-gc + dashboard UX | 1.13.0 |
| #90 | feat: worktree dispatch, watcher auto-gc, status fix | 1.14.0 |
| #91 | feat: dashboard UX round 2 — activity feed, notifications, HTML extraction | 1.15.0 |
| #92 | docs: update commands and dashboard features | 1.15.1 |
| #93 | fix: dashboard var(--fg) and test workflow field | 1.15.1 |

---

## Remaining Tasks

| Task | Status | Note |
|------|--------|------|
| `feat.task-lifecycle-ship` | `todo` | Blocked — auto-commit in lifecycle, deferred until worktree proves insufficient |

---

## Known Issues

- `uv pip install -e .` caches stale metadata — use `python -m pip install -e .` for reliable version detection
- Dashboard guard (`pgrep -f dashboard-ui`) detects background shell processes as running instances — occasional false positives on restart

---

## Next Session Starting Point

```
shux status      # should show 0 issues
shux recap       # see this session's activity
shux contract    # 1 remaining task (feat.task-lifecycle-ship)
shux dashboard   # verify all new features render correctly
```
