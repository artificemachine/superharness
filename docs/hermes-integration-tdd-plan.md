# Hermes → Superharness: Combined Implementation Plan (TDD)

> Merged from: `hermes-agent/docs/hermes_to_superharness_spec_plan.md` + `docs/hermes-integration-tdd-plan.md`
> Date: 2026-04-28

## Overview

8 features extracted from hermes-agent into superharness, organized in 4 phases. Each iteration follows RED → GREEN → REFACTOR. All extractions are additive — they wrap existing behavior, never replace it.

---

## Phase 1: Security Guard

### Iteration 1.1: Dangerous Command Detection

**Source:** `hermes-agent/tools/approval.py` (lines 24-93, 100-116)
**Effort:** ~2 hours

**RED:** Write `tests/unit/test_guard.py`:
- `test_detect_rm_rf` — `rm -rf /` → dangerous
- `test_detect_curl_pipe_bash` — `curl ... | bash` → dangerous
- `test_detect_fork_bomb` — `:(){ :|:& };:` → dangerous
- `test_detect_chmod_777` — `chmod 777 /etc` → dangerous
- `test_detect_dd_overwrite` — `dd if=/dev/zero of=/dev/sda` → dangerous
- `test_safe_echo` — `echo hello` → safe
- `test_safe_ls` — `ls -la` → safe
- `test_approval_state_session` — approve once, check is_approved
- `test_approval_state_permanent` — approve permanent, survives session reset

**GREEN:**
- `src/superharness/guard/__init__.py` (5 lines)
- `src/superharness/guard/dangerous_patterns.py` (55 lines) — 25 regex patterns
- `src/superharness/guard/detector.py` (20 lines) — `detect_dangerous_command(cmd) -> (bool, str)`
- `src/superharness/guard/state.py` (30 lines) — per-session approval tracking

**REFACTOR:**
- Wire into handoff writer: scan terminal history before persisting
- Wire into ledger: flag dangerous commands found in agent output
- New CLI: `shux guard check <command>`

---

### Iteration 1.2: Credential Redaction

**Source:** `hermes-agent/agent/redact.py`
**Effort:** ~1 hour

**RED:** Write `tests/unit/test_redact.py`:
- `test_redact_api_key` — `sk-abc123` → `[REDACTED]`
- `test_redact_bearer_token` — `Bearer eyJ...` → `Bearer [REDACTED]`
- `test_redact_password` — `password=secret` → `password=[REDACTED]`
- `test_redact_db_url` — `postgres://user:pass@host` → `postgres://user:[REDACTED]@host`
- `test_redact_private_key` — PEM block → `[REDACTED]`
- `test_redact_phone` — `+1234567890` → `[REDACTED]`
- `test_preserve_safe_text` — plain text unchanged

**GREEN:**
- `src/superharness/guard/redact.py` (90 lines) — pattern set + `redact(text) -> str`

**REFACTOR:**
- Wrap handoff writer: `content = redact(content)` before write
- Wrap ledger append: `redact()` before persisting
- Wrap task report: `redact()` before saving

---

## Phase 2: Safety Net

### Iteration 2.1: Checkpoint / Rollback

**Source:** `hermes-agent/tools/checkpoint_manager.py`
**Effort:** ~3 hours

**RED:** Write `tests/unit/test_checkpoint.py`:
- `test_snapshot_creates_git_ref` — `snapshot()` creates a git stash/tag
- `test_rollback_restores_files` — `rollback()` reverts to snapshot state
- `test_prune_old_removes_stale` — `prune_old()` removes snapshots > 24h
- `test_snapshot_idempotent` — second snapshot on same task is no-op
- `test_rollback_nonexistent_fails` — rollback without snapshot raises

**GREEN:**
- `src/superharness/guard/checkpoint.py` (100 lines):
  - `snapshot(project_dir, task_id)` — git stash with task tag
  - `rollback(project_dir, task_id)` — git stash pop
  - `prune_old(project_dir, max_age_hours=24)` — remove stale stashes
  - All use `shux worktree` for consistency

**REFACTOR:**
- Pre-task hook: snapshot before `shux delegate` spawns agent
- Failed verification: `shux verify <id> --rollback`
- New CLI: `shux checkpoint list`, `shux checkpoint restore <id>`

---

### Iteration 2.2: Smart Approval State (from my audit)

**RED:** Write `tests/unit/test_approval_state.py`:
- `test_approve_session_scoped` — approve for session, reset on new session
- `test_approve_permanent_persists` — permanent approval survives restart
- `test_auto_approve_low_risk` — low-risk commands auto-approved
- `test_thread_safe_concurrent` — concurrent access doesn't corrupt
- `test_legacy_key_aliasing` — old pattern keys still match

**GREEN:**
- Extend `src/superharness/guard/state.py` (adds ~40 lines):
  - `ApprovalState` class with `_session_approved`, `_permanent_approved`
  - `_check_risk(command)` — heuristic classifier
  - Persistence via `~/.superharness/approvals.json`

**REFACTOR:**
- Wire into `_auto_peer_approve_plans`: low-risk tasks auto-approved
- Wire into `shux guard check`: shows approval status

---

## Phase 3: Intelligence

### Iteration 3.1: Skills for Cross-Agent Handoffs

**Source:** `hermes-agent/agent/skill_commands.py`
**Effort:** ~4 hours

**RED:** Write `tests/unit/test_skills.py`:
- `test_save_skill_from_task` — save task workflow as skill YAML
- `test_load_skill_by_name` — load and parse skill YAML
- `test_discover_skills_by_tag` — find skills matching tags
- `test_skill_injection_in_prompt` — skill included in delegation context
- `test_invalid_skill_yaml_fails` — bad YAML raises validation error
- `test_skill_list_all` — list all saved skills
- `test_skill_delete_removes_file` — delete removes from disk

**GREEN:**
- `protocol/skills.md` (60 lines) — skill YAML format spec
- `src/superharness/skills/__init__.py` (5 lines)
- `src/superharness/skills/loader.py` (50 lines) — YAML loading + validation
- `src/superharness/skills/discovery.py` (40 lines) — tag matching, search

**REFACTOR:**
- `shux close <id> --save-skill <name>` — extract workflow as skill
- `shux delegate <id>` — include matching skill in context
- New CLI: `shux skills list`, `shux skills show`, `shux skills delete`

---

### Iteration 3.2: Smart Dispatch Routing

**Source:** `hermes-agent/agent/smart_model_routing.py`
**Effort:** ~3 hours

**RED:** Write `tests/unit/test_smart_routing.py`:
- `test_classify_simple_task` — short description → low complexity
- `test_classify_complex_task` — multi-step, multi-file → high complexity
- `test_route_simple_to_mini` — low complexity → mini tier suggestion
- `test_route_complex_to_max` — high complexity → max tier suggestion
- `test_budget_aware_routing` — low budget → downgrade tier

**GREEN:**
- Extend `src/superharness/engine/model_router.py` (adds ~80 lines):
  - `classify_complexity(task) -> str` — simple/medium/complex
  - `suggest_tier(complexity, budget_remaining) -> str` — mini/standard/max

**REFACTOR:**
- `shux auto-dispatch` uses complexity + budget for model selection
- Budget-aware: if `budget.daily_limit` is low, prefer cheaper models

---

## Phase 4: Reliability & Observability

### Iteration 4.1: Event Hook System

**RED:** Write `tests/unit/test_hooks.py`:
- `test_parse_hook_yaml` — valid HOOK.yaml parses
- `test_hook_expired_skipped` — expired hook not loaded
- `test_fire_event_calls_handler` — event triggers handler
- `test_handler_error_doesnt_block` — one handler crashes, others run
- `test_task_lifecycle_hooks` — task:created, task:delegated, task:completed, task:failed fire

**GREEN:**
- `src/superharness/engine/hooks.py` (100 lines):
  - `HookDef` dataclass (name, events, handler_fn, expires)
  - `HookRegistry` with `register()`, `fire(event, data)`
  - `load_hooks_from_dir()` — scans `~/.superharness/hooks/`
  - Built-in events: `hook_events.py`

**REFACTOR:**
- Fire hooks from watcher: `task:delegated`, `task:completed`, `task:failed`, `task:closed`

---

### Iteration 4.2: Proactive Session Flush

**RED:** Write `tests/unit/test_session_flush.py`:
- `test_detect_expiring_task` — task within warning window returns True
- `test_flush_in_progress_context` — saves current state to handoff
- `test_skip_already_flushed` — doesn't double-write
- `test_watcher_runs_flush_before_timeout` — flush fires before lifecycle reconcile

**GREEN:**
- `src/superharness/engine/session_flush.py` (50 lines):
  - `check_expiring(project_dir, warning_minutes=15) -> list[str]`
  - `flush_task(project_dir, task_id)` — write partial work to handoff

**REFACTOR:**
- Wire into watcher cycle BEFORE lifecycle reconciler
- Configurable: `profile.yaml` → `flush_warning_minutes: 15`

---

## Summary

| Phase | Iteration | Pattern | Tests | Hours |
|-------|-----------|---------|-------|-------|
| 1 | 1.1 | Dangerous Command Detection | 9 | 2 |
| 1 | 1.2 | Credential Redaction | 7 | 1 |
| 2 | 2.1 | Checkpoint/Rollback | 5 | 3 |
| 2 | 2.2 | Smart Approval State | 5 | 2 |
| 3 | 3.1 | Skills for Handoffs | 7 | 4 |
| 3 | 3.2 | Smart Dispatch Routing | 5 | 3 |
| 4 | 4.1 | Event Hook System | 5 | 2 |
| 4 | 4.2 | Proactive Session Flush | 4 | 2 |
| **Total** | | | **47** | **19** |

Files: ~13 new, ~5 modified. Lines: ~1,100 new.
