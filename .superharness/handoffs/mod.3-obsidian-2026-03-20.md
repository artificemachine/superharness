---
task_id: mod.3-obsidian
date: 2026-03-20
from: claude-code
to: claude-code
status: done
---

# Handoff: mod.3-obsidian — Obsidian module (vault integration)

## Summary

Completed iteration 3 of the module system: Obsidian vault integration module.

The module enables automatic saving of task handoffs to an Obsidian vault as markdown notes with YAML frontmatter. It includes auto-detection of vault paths, secret redaction, and integration with the on_close lifecycle hook.

## What was done

### Files created
- `src/superharness/modules/actions/__init__.py` — actions package
- `src/superharness/modules/actions/obsidian.py` — Obsidian action implementation
- `src/superharness/module_templates/obsidian.yaml` — module template
- `tests/unit/test_module_obsidian.py` — 8 unit tests

### Files modified
- `src/superharness/modules/__init__.py` — registered obsidian_write_note action

### Implementation details

**obsidian.py** provides:
1. `detect_vault(path)` — auto-detect Obsidian vault at known paths or explicit path
2. `is_mcp_available()` — check for MCP server (stub, returns False for now)
3. `redact_secrets(text)` — redact API keys, GitHub tokens, AWS keys, private IPs
4. `obsidian_write_note(context, settings)` — main on_close hook action

**obsidian.yaml** template includes:
- Auto-detection paths: `~/Documents/OBSIDIAN_ICLOUD/coredev/`, `~/Documents/Obsidian/`, `~/Obsidian/`
- Optional MCP: `obsidian-semantic`
- Settings: vault_subfolder `1_ai/{project_name}/`, filename pattern `{project_name}-{date}-{title}.md`
- Secret redaction enabled by default

**Secret redaction patterns:**
- API keys: `sk-*`, generic `api_key=*`
- GitHub tokens: `ghp_*`, `gho_*`, `ghu_*`, `ghs_*`
- AWS keys: `AKIA*`
- Private IPs: 10.x.x.x, 172.16-31.x.x, 192.168.x.x
- Generic tokens and bearer tokens

## Acceptance criteria

✅ **All acceptance criteria met:**
- 8 tests pass in test_module_obsidian.py

## Test results

```
pytest tests/unit/test_module_obsidian.py -v
============================== 8 passed in 0.04s ===============================

All 28 module tests pass (loader: 5, obsidian: 8, registry: 8, runner: 7)
```

## Dependencies

**Depends on:**
- mod.2-registry (done) — module registry and enhance CLI

**Enables:**
- Users can now run `shux enhance enable obsidian` to save handoffs to vault
- Notes are auto-written to `vault/1_ai/{project}/` on task close
- Secrets are automatically redacted from saved notes

## Next steps

**Suggested next task:** mod.4-autoschedule (auto-delegate tasks on schedule)

**Integration note:** To wire the Obsidian module into the close command:
1. Import `run_hooks` from `modules.runner`
2. After close logic, call: `run_hooks("on_close", context, project_dir)`
3. Context should include: task_id, summary, project_name, actor

**MCP TODO:** When MCP integration is ready, update `is_mcp_available()` to check if `mcp__obsidian-semantic__write_file` is callable.

## Handoff to

**Next actor:** claude-code (for mod.4-autoschedule or integration work)

---

*Handoff created: 2026-03-20*
*Protocol: superharness v1.0.0*
