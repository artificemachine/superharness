# Handoff — superharness v1.44.2 → v1.45.0

> Date: 2026-04-29
> Branch: `main` (unpublished fixes)
> Published: v1.44.2 on PyPI

## What was accomplished

### YAML→SQLite Migration (Complete)
All runtime state reads/writes use SQLite. YAML is export-only via `shux export-yaml`.
- ~1,000 lines of dead YAML code removed
- `inbox_gc`, `inbox_recover`, `zombie_reconcile`, `paused_reconcile`, `discussion_reconcile` all SQLite-native
- `state_reader._get_backend()` always returns `sqlite_only`
- `state_writer` mirror functions removed; keep `mirror_task_dict`/`mirror_inbox_item_dict` as SQLite shims

### Hermes Cherry-Pick (8 features from hermes-agent)
```
src/superharness/guard/
├── dangerous_patterns.py  — 25 shell attack patterns
├── detector.py            — detect_dangerous_command()
├── state.py               — ApprovalState with risk classification
├── redact.py              — Credential redaction (10 patterns)
└── checkpoint.py          — Git stash checkpoint/rollback

src/superharness/skills/
└── loader.py              — Skill YAML save/load/discover

src/superharness/engine/
├── hooks.py               — Event hook system (HookRegistry)
└── session_flush.py       — Proactive flush before lifecycle timeout
```

### Auto-Mode Gaps Closed
- **Peer approval**: `_auto_peer_approve_plans` dispatches plan review to different max-tier agent
- **Stale task GC**: `_auto_archive_stale_tasks` archives tasks with no handoff after 4h
- **Plan-only timeout**: 15-min kill for stuck plan-only tasks
- **Task log analyzer**: detects stuck agents (no activity >15min → fail)
- **Escalation classifier**: infra bug vs implementation fail
- **Per-agent budget**: `check_agent_budget()` before dispatch
- **Self-diagnosis**: `_self_diagnosis()` on watcher startup
- **Pipeline health check**: `shux pipeline-check`
- **Review notes**: auto-mode appends review context to completed tasks

### Watcher Enhancements
- `auto_enqueue_todo` / `auto_enqueue_approved` recreated (were deleted by YAML cleanup)
- `--once` mode for hot-reload on each cycle
- All errors logged to `.superharness/watcher-errors.log`
- Disk guard: launcher log rotation at 200 files
- Auto-upgrade detection in daemon

### Dashboard Improvements
- Review mode tabs (All / Needs Review / In Progress / Auto-handled / Stale)
- Watcher errors panel (collapsible, copy button, auto-refresh)
- "contract tasks" panel (renamed from "tasks")
- Sort button (default / A-Z / status / owner)
- Live log deep-cleaning (ANSI, box-drawing, Nerd Font, non-ASCII stripped)
- Activity summary in task report (Phase, Errors, Files changed)
- Discussion agent activity panel
- Recent failures copy button

### Discussion System
- File-based submission workflow (prompts generated at `.superharness/discussions/<id>/prompt-<agent>.md`)
- Agents submit via `shux discuss submit` (CLI) or module directly
- Round submissions synced to SQLite
- Consensus close button in dashboard panel
- Discussion state sync to SQLite on creation

### Bug Fixes
- Dashboard version mismatch: log warning instead of restart loop
- Stale `operator-state.json`: dead PID detection + cleanup
- Python path: daemon/dispatch pinned to pipx Python (prevents `ModuleNotFoundError: yaml`)
- `_get_python()` helper added to dispatch
- `plan_only=False` for discussion round tasks (auto-dispatch + auto-retry)
- `review_requested_at` column added to tasks schema

## What's NOT done (known issues)

### 1. Discussion auto-dispatch broken for Claude Code
Claude Code is inherently interactive. Discussion agents dispatched via inbox dispatch get stuck at prompts.
**Workaround**: Use file-based submission (prompts generated, submit via CLI).
**Fix needed**: Implement non-interactive dispatch mode for discussions (use `-p` flag for Claude).

### 2. pipx version is stale (v1.44.2)
Many fixes exist only in source code (`main` branch), not in pipx install.
**Needed**: Bump to v1.44.3 and publish to PyPI.

### 3. Dashboard needs uv run for latest features
The pipx-installed `superharness dashboard` runs v1.44.2 (old code).
**Workaround**: `uv run superharness dashboard --port 8787 --project ...`
**Fix needed**: Publish v1.44.3.

### 4. Operator CLI blocks on `shux operator start`
`monitor_and_recover` runs in main thread. Use `shux dashboard` standalone instead.
**Workaround**: `nohup uv run superharness dashboard --port 8787 ... &`

### 5. Discussion SQLite sync was reverted
The `_sync_discussion_to_sqlite` calls were in a commit that introduced indentation errors.
**Reverted**: Clean `discussion.py` committed. Need to re-apply the SQLite sync carefully.

### 6. Tests needed
- `tests/unit/test_anti_hang.py`: 7 tests (passing)
- Need: E2E smoke test, pipeline integration test, discussion submission test

## Key Commands

```bash
# Development (use source code)
uv sync --reinstall
uv run shux status --active         # verbose per-task view
uv run shux pipeline-check          # health probe (11 checks)
uv run superharness dashboard --port 8787 --no-open --project .

# Production (pipx)
shux status
shux daemon start
shux daemon restart
shux dashboard --port 8787

# Discussion submissions (file-based)
shux discuss submit \
  --discussion <id> --agent <agent> --round 1 \
  --verdict consensus --position "..." \
  --points-file <path>

# Export YAML snapshots
shux export-yaml --all

# Check errors
tail -f .superharness/watcher-errors.log
```

## Next Priority (v1.45.0)

1. **Publish v1.44.3** with all fixes on `main`
2. **Refactor dashboard** — split 3100-line monolith into server/api/static
3. **File-based discussion dispatch** — non-interactive mode for Claude Code
4. **Re-apply discussion SQLite sync** — re-add `_sync_discussion_to_sqlite` calls
5. **E2E smoke tests** — dynamic pipeline probe that creates a test task
6. **OpenTelemetry tracing** — for auto-mode pipeline diagnostics

## Active Processes (after restart)

```bash
# Daemon (watcher cycles)
shux daemon start

# Dashboard (standalone)
nohup uv run superharness dashboard --port 8787 --no-open --project . > /tmp/dash.log 2>&1 &

# Verify
uv run shux status --active
```

## File Locations

| What | Where |
|------|-------|
| Watcher errors | `.superharness/watcher-errors.log` |
| Daemon logs | `.superharness/launcher-logs/daemon.out.log` |
| Discussion prompts | `.superharness/discussions/<id>/prompt-<agent>.md` |
| Guard modules | `src/superharness/guard/` |
| Skills | `src/superharness/skills/` |
| Hooks config | `.superharness/hooks/<name>/HOOK.yaml` |
| Pipeline check | `src/superharness/commands/pipeline_check.py` |
| Anti-hang tests | `tests/unit/test_anti_hang.py` |
