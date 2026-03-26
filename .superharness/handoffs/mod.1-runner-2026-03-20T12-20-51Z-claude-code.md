---
task_id: mod.1-runner
title: Module runner (lifecycle hooks)
from: claude-code
to: next-agent
timestamp: 2026-03-20T12:20:51Z
status: done
contract_id: initial-setup
project_path: /Users/airm2max/DevOpsSec/superharness
---

# Task: mod.1-runner — Module runner (lifecycle hooks)

## Status: ✅ DONE

All 7 acceptance criteria tests passing.

## What Was Done

### Created Files
1. **tests/unit/test_module_runner.py** — TDD RED phase with 7 tests
   - `test_on_close_fires_for_enabled_module` — verifies hook execution
   - `test_on_close_skips_disabled_module` — verifies disabled modules ignored
   - `test_on_verify_fires` — verifies on_verify hook
   - `test_on_continue_fires` — verifies on_continue hook
   - `test_module_failure_does_not_block_close` — fail-safe behavior
   - `test_multiple_modules_all_fire` — multiple module support
   - `test_hook_receives_context` — context and settings passed correctly

2. **src/superharness/modules/runner.py** — GREEN phase implementation
   - `run_hooks(event, context, project_dir)` — main entry point
   - `register_action(name, func)` — action registry for hook implementations
   - `_ACTION_REGISTRY` — maps action names to callables
   - `LIFECYCLE_EVENTS` — defines all supported events
   - Fail-safe design: module errors logged, don't block task completion

### Design Decisions

1. **Action Registry Pattern**
   - Module YAML declares `action: action_name`
   - Actions registered via `register_action()` by action modules
   - Decouples hook execution from action implementation
   - Makes testing trivial (mock the registry)

2. **Lifecycle Events**
   - Defined in `LIFECYCLE_EVENTS` list
   - Current: `on_close`, `on_verify`, `on_continue`, `on_delegate`, `on_watcher_tick`
   - Future modules can add new events by updating this list

3. **Fail-Safe Execution**
   - Module errors never block the main task flow
   - All exceptions caught and logged
   - Results include `success: bool` and optional `error` field
   - Aligns with "modules are enhancements, not requirements" principle

4. **Context Passing**
   - Every hook receives `(context: dict, settings: dict)`
   - Context = task info (task_id, summary, project_dir, actor, etc.)
   - Settings = module-specific config from YAML
   - Clean separation of concerns

## Test Results

```
$ pytest tests/unit/test_module_runner.py -v
tests/unit/test_module_runner.py::TestModuleRunner::test_on_close_fires_for_enabled_module PASSED [ 14%]
tests/unit/test_module_runner.py::TestModuleRunner::test_on_close_skips_disabled_module PASSED [ 28%]
tests/unit/test_module_runner.py::TestModuleRunner::test_on_verify_fires PASSED [ 42%]
tests/unit/test_module_runner.py::TestModuleRunner::test_on_continue_fires PASSED [ 57%]
tests/unit/test_module_runner.py::TestModuleRunner::test_module_failure_does_not_block_close PASSED [ 71%]
tests/unit/test_module_runner.py::TestModuleRunner::test_multiple_modules_all_fire PASSED [ 85%]
tests/unit/test_module_runner.py::TestModuleRunner::test_hook_receives_context PASSED [100%]

7 passed in 0.05s
```

## Next Steps (for mod.2-registry)

1. **Wire runner into existing commands:**
   - `src/superharness/commands/close.py` — add `run_hooks("on_close", ...)` after close
   - `src/superharness/commands/verify.py` — add `run_hooks("on_verify", ...)` after verify
   - Create or update `continue` command — add `run_hooks("on_continue", ...)`

2. **Create module registry:**
   - `src/superharness/modules/registry.py` — enable/disable/list modules
   - `src/superharness/cli.py` — add `shux enhance` command group
   - Template directory: `src/superharness/module_templates/`

3. **Tests for mod.2-registry:**
   - 8 tests defined in `docs/plan-module-system.md` lines 147-172

## Dependencies

- **Depends on:** mod.0-loader (done)
- **Blocks:** mod.2-registry, all subsequent module iterations

## Files Modified

- `.superharness/contract.yaml` — marked mod.1-runner as done, added test_types
- `.superharness/ledger.md` — appended 3 entries

## Architecture Notes

The runner is intentionally minimal:
- **No conditional logic** — modules control when they fire via YAML `hooks` section
- **No dependency resolution** — modules fire in YAML load order (alphabetical filename)
- **No async** — hooks run synchronously, keep it simple for now
- **No rollback** — fire-and-forget, modules are side effects

This design makes it easy to reason about and test. Future enhancements (ordering, dependencies, async) can be added when needed without breaking existing modules.

## Security Compliance

✅ No secrets, tokens, or credentials in code or tests
✅ No hardcoded paths (all use `tmp_path` fixture)
✅ All tests use mock actions, no real external calls
✅ Follows fail-safe principle (errors don't crash the system)

---

**Ready for next iteration: mod.2-registry (Registry + shux enhance CLI)**
