# Hermes Cherry-Pick Implementation: TDD Plan

> Date: 2026-04-28
> Source audit: `docs/hermes-cherry-pick-audit.md`
> Goal: Implement top 5 cherry-pick patterns into superharness using TDD

## Iteration 0: Test harness setup (shared foundation)

**RED:** No tests exist for new modules.

**GREEN:**
- Create `tests/unit/test_tool_registry.py` — empty test file with `test_registry_singleton`
- Create `tests/unit/test_approval_state.py` — empty test file with `test_session_approved_defaults`
- Create `tests/unit/test_hooks.py` — empty test file with `test_hook_yaml_parse`
- All 3 test files have one failing test each (import non-existent module)

**REFACTOR:** None (initial setup).

---

## Iteration 1: Tool Registry

**RED:** Write tests for `superharness.engine.tool_registry`:
- `test_register_single_tool` — register a tool, verify it appears in registry
- `test_register_duplicate_rejected` — registering same name twice raises error
- `test_get_tool_by_name` — retrieve registered tool
- `test_list_by_category` — filter tools by category
- `test_dispatch_tool_call` — call a registered function through the registry
- `test_missing_tool_raises` — getting unregistered tool raises KeyError
- `test_singleton_pattern` — `get_registry()` always returns same instance

**GREEN:**
- `engine/tool_registry.py`:
  - `ToolDef` dataclass (name, fn, schema, category, help_text, requires_env)
  - `ToolRegistry` class with `register()`, `get()`, `list()`, `dispatch()`
  - `get_registry()` singleton factory
  - Each method validates inputs
- All 7 tests pass

**REFACTOR:**
- Inline `cli.py` `_cmd()` calls into tool registry registration
- Migrate 3 commands as proof: `shux contract`, `shux status`, `shux auto-dispatch`
- Verify existing tests still pass after refactor

---

## Iteration 2: Approval State

**RED:** Write tests for `superharness.engine.approval_state`:
- `test_session_approved_starts_empty` — new session has no approvals
- `test_approve_once` — approve a command for current session
- `test_approve_session` — approve all commands for session
- `test_approve_permanent` — add to permanent allowlist
- `test_deny_command` — denied command re-prompts
- `test_legacy_key_aliasing` — old pattern key still matches
- `test_thread_safety` — concurrent accesses don't corrupt state
- `test_persistence` — permanent approvals survive restart (write to config)
- `test_auto_approve_low_risk` — Smart Approvals pattern: low-risk commands auto-approved

**GREEN:**
- `engine/approval_state.py`:
  - `ApprovalState` class with `_session_approved`, `_permanent_approved` sets
  - `approve(command, scope)`, `deny(command)`, `is_approved(command)`
  - `_check_risk(command)` — simple heuristic risk classifier (path patterns, command categories)
  - Thread-safe via `threading.Lock()`
  - Persistence via `~/.superharness/approvals.json`
  - Legacy key mapping dict
- All 9 tests pass

**REFACTOR:**
- Wire approval state into `_auto_peer_approve_plans` in `inbox_watch.py`
- Low-risk tasks (typo fixes, config changes) auto-approved
- High-risk tasks (refactors, new features) still need peer review

---

## Iteration 3: Event Hook System

**RED:** Write tests for `superharness.engine.hooks`:
- `test_parse_hook_yaml` — parse HOOK.yaml with events list
- `test_hook_yaml_missing_events_fails` — invalid YAML raises
- `test_register_hook` — register a hook handler
- `test_fire_event_calls_handler` — firing an event invokes registered handler
- `test_fire_event_with_no_handlers` — event with no handlers doesn't crash
- `test_handler_error_doesnt_block` — handler raises, other handlers still run
- `test_multiple_handlers_same_event` — multiple handlers fire on same event
- `test_builtin_events` — verify all built-in events exist (task:created, task:delegated, task:completed, task:failed, task:closed)

**GREEN:**
- `engine/hooks.py`:
  - `HookDef` dataclass (name, events, handler_fn)
  - `HookRegistry` class with `register()`, `fire(event, data)`
  - `load_hooks_from_dir()` — scans `~/.superharness/hooks/` for `HOOK.yaml` + `handler.py`
  - `HOOK_SCHEMA` — YAML schema validation
  - Built-in events module: `engine/hook_events.py` with constants
- All 8 tests pass

**REFACTOR:**
- Fire hooks from watcher at key lifecycle points (task:delegated, task:completed, task:failed)
- Fire hooks from auto-close (task:closed)
- Fire hooks from peer-approve (task:approved, task:rejected)

---

## Iteration 4: Proactive Session Flush

**RED:** Write tests for `superharness.engine.session_flush`:
- `test_detect_expiring_task` — task nearing timeout returns True
- `test_flush_partial_work` — flushes in_progress task context to handoff
- `test_skip_flushed_task` — already-flushed task skips
- `test_watcher_integrates_flush` — watcher calls flush before lifecycle reconciler

**GREEN:**
- `engine/session_flush.py`:
  - `check_expiring(project_dir, warning_minutes=15)` — finds tasks within warning threshold of lifecycle timeout
  - `flush_task(project_dir, task_id)` — writes current context to handoff file
  - `is_flushed(task_id)` — checks if task was already flushed in this session
  - Wired into watcher cycle BEFORE lifecycle reconciler
- All 4 tests pass

**REFACTOR:**
- Add `flush_warning_minutes` to `profile.yaml` for configurable warning window

---

## Iteration 5: Git Worktree Enhancement

**RED:** Write tests for `superharness.engine.worktree_ops`:
- `test_prune_stale_worktrees` — removes worktrees older than 24h with no changes
- `test_worktree_include_pattern` — copies `.worktreeinclude` files
- `test_clean_removal_on_exit` — worktree removed if no uncommitted changes
- `test_keep_dirty_worktree` — worktree with changes not removed
- `test_concurrent_worktree_safety` — two dispatches don't collide on same worktree

**GREEN:**
- Extend `engine/worktree_ops.py`:
  - `prune_stale()` — scans dispatch worktrees, removes stale ones
  - `resolve_includes()` — reads `.worktreeinclude`, copies matching files
  - `cleanup_worktree(path)` — removes worktree if clean
  - All functions use `shux worktree` CLI for consistency
- All 5 tests pass

**REFACTOR:**
- Wire `prune_stale()` into watcher cycle (between auto_enqueue and dispatch)
- Wire `cleanup_worktree()` into `_run_dispatch_cmd()` post-dispatch

---

## Summary

| Iteration | Pattern | Tests | Effort |
|-----------|---------|-------|--------|
| 0 | Test harness | 3 | 1 session |
| 1 | Tool Registry | 7 | 1-2 sessions |
| 2 | Approval State | 9 | 2-3 sessions |
| 3 | Event Hook System | 8 | 2 sessions |
| 4 | Proactive Session Flush | 4 | 1-2 sessions |
| 5 | Git Worktree Enhancement | 5 | 1-2 sessions |
| **Total** | | **36** | **8-12 sessions** |
