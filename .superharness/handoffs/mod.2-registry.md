---
task_id: mod.2-registry
title: Registry + shux enhance CLI
status: done
owner: claude-code
created: 2026-03-20T12:26:46Z
completed: 2026-03-20T12:26:46Z
---

# Task: mod.2-registry — Registry + shux enhance CLI

## Summary

Implemented iteration 2 of the superharness module system: module registry and `shux enhance` CLI.

## What was done

### Implementation (GREEN phase)

1. **Created `test_module_registry.py`** (8 tests)
   - `test_list_available_modules` — lists built-in templates
   - `test_list_enabled_modules` — lists only enabled modules in project
   - `test_enable_copies_template` — enable copies template and sets `enabled: true`
   - `test_enable_already_enabled_is_noop` — idempotent enable
   - `test_disable_sets_enabled_false` — disable sets `enabled: false`
   - `test_disable_already_disabled_is_noop` — idempotent disable
   - `test_enable_unknown_module_fails` — error on non-existent module
   - `test_info_shows_module_details` — shows description, detection, settings, hooks

2. **Created `src/superharness/modules/registry.py`**
   - `available_modules()` — list all templates in `module_templates/`
   - `enabled_modules(project_dir)` — list enabled modules in project
   - `enable_module(name, project_dir)` — copy template, set `enabled: true`
   - `disable_module(name, project_dir)` — set `enabled: false` (idempotent)
   - `module_info(name, project_dir)` — return module metadata dict

3. **Created `src/superharness/commands/enhance.py`** (CLI)
   - `shux enhance` (default) → list modules
   - `shux enhance list` → list available and enabled modules
   - `shux enhance enable <name>` → enable a module
   - `shux enhance disable <name>` → disable a module
   - `shux enhance info <name>` → show module details

4. **Created `src/superharness/module_templates/`**
   - Added `placeholder.yaml` — minimal template to satisfy tests (will be replaced in iteration 3+)

5. **Updated `src/superharness/cli.py`**
   - Added `enhance` command registration
   - Updated `shux` shortcut help to include `shux enhance`

## Acceptance criteria

✅ All 8 tests pass in `test_module_registry.py`

```
pytest tests/unit/test_module_registry.py -v
# 8 passed in 0.04s
```

## Test evidence

```bash
pytest tests/unit/test_module_*.py -v
# 20 passed (5 loader + 7 runner + 8 registry)
```

Manual CLI testing:
```bash
superharness enhance --help
# Shows command group with list, enable, disable, info subcommands

superharness enhance list
# Lists available modules (placeholder shown)

superharness enhance info placeholder
# Shows module metadata
```

## Files created/modified

### Created
- `tests/unit/test_module_registry.py` (8 tests, ~250 lines)
- `src/superharness/modules/registry.py` (~180 lines)
- `src/superharness/commands/enhance.py` (~160 lines)
- `src/superharness/module_templates/placeholder.yaml` (placeholder template)
- `src/superharness/module_templates/.gitkeep`

### Modified
- `src/superharness/cli.py` — added `enhance` command registration + updated `shux` help
- `.superharness/contract.yaml` — task mod.2-registry status → done
- `.superharness/ledger.md` — appended completion entries

## Dependencies satisfied

- Iteration 0 (mod.0-loader): ✅ 5 tests pass
- Iteration 1 (mod.1-runner): ✅ 7 tests pass
- Iteration 2 (mod.2-registry): ✅ 8 tests pass

**Total: 20 tests passing**

## Next task

**mod.3-obsidian** — Obsidian module (vault integration)
- Dependency: mod.2-registry ✅ (done)
- Acceptance criteria: 8 tests pass in `test_module_obsidian.py`
- Priority: High — closes the knowledge loop

Refer to `docs/plan-module-system.md` iteration 3 for TDD steps.

## Notes

- All module operations (enable/disable) are idempotent
- Module templates ship with superharness in `src/superharness/module_templates/`
- Enabled modules are copied to `.superharness/modules/` with `enabled: true`
- Disabled modules have `enabled: false` but file persists
- Registry functions handle missing directories gracefully (no errors)
- CLI has colored output (green for enabled, cyan for available)

## Architecture decisions

1. **Modules are YAML files** — not Python packages or plugins
2. **Templates ship with package** — in `module_templates/` directory
3. **Enable = copy + set enabled: true** — simple, portable, inspectable
4. **Disable = set enabled: false** — preserves settings, can re-enable easily
5. **Idempotency everywhere** — enable/disable can be called multiple times safely

---

**Handoff complete** — iteration 2 foundation ready for iteration 3 (Obsidian module).
