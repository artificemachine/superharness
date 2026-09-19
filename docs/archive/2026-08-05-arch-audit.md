# Architecture Audit — superharness

**Date:** 2026-08-05
**Scope:** Broad structural review
**Auditor:** Codex

## Summary

The core state design is materially stronger than the public architecture narrative: SQLite uses versioned migrations, savepoint rollback, foreign keys, indexed operational tables, XDG-aware resolution, and online backup support. The main architectural risk is not the database itself; it is the gap between that design and a 4,788-line watcher that owns many independent concerns. Public documentation also contains several superseded or aspirational architectures without a clear boundary, so contributors cannot reliably infer the current command and state model.

## CRITICAL — fix before next deploy

None found.

## HIGH — fix before scale

### Watcher orchestration remains a god module

- Evidence: `src/superharness/commands/inbox_watch.py` is 4,788 lines and directly imports/opens the database at many distinct call sites (for example lines 66-68, 2010-2058, and 4646). It mixes lifecycle reconciliation, dispatch, discussion flow, liveness, telemetry, and direct SQL.
- Risk: changes to one background responsibility require editing the same high-churn module, making race and regression isolation expensive.
- Recommended fix: split one cohesive slice at a time behind existing engine seams—start with a narrow reconciliation service and explicit DAO boundary; preserve the command as composition only.
- Suggested phase: dedicated watcher decomposition, with concurrent-cycle tests per extracted slice.

## MEDIUM — recoverable technical debt

### Current architecture documentation contradicts its own SQLite migration note

- Evidence: `docs/ARCHITECTURE.md:29` calls SQLite the runtime source of truth, but lines 42-48 describe engine YAML operations; its diagram starts at line 107 with YAML-era scripts/state, and line 75 still names a project-local database layout. The runtime resolver instead uses XDG/override precedence in `src/superharness/utils/paths.py:49-70` and `resolve_active_state_db_path` at lines 136-178.
- Risk: operators may inspect or modify exports as if they were live state, or diagnose the wrong database path.
- Recommended fix: replace the legacy layer diagram and state section with the canonical resolver, SQLite DAO boundary, and export-only YAML explanation; label retained historical material as archival.
- Suggested phase: documentation correction before the next public release.

### Concept documentation advertises command surfaces that do not exist

- Evidence: `docs/CONCEPT-notifications-and-state-isolation.md:455-489` presents `shux state {dump,schema,size,vacuum,export,diff,shell,info}` as available. The registered CLI commands at `src/superharness/cli.py:140-165` contain `backup-state`, `archive-yaml`, and `export-yaml`, but no `state` command.
- Risk: a new user following the public design document reaches nonexistent commands and cannot distinguish a proposal from supported functionality.
- Recommended fix: mark the document as a proposal, or rewrite those sections to the implemented CLI.
- Suggested phase: same public-documentation correction.

## LOW — nice-to-have polish

### The runtime has multiple direct-SQL command paths despite DAO modules

- Evidence: `src/superharness/commands/inbox_watch.py` repeatedly imports `get_connection` and issues SQL, while task/inbox DAO modules already exist under `src/superharness/engine/`.
- Risk: new constraints or migration behaviour can be implemented inconsistently across direct call sites.
- Recommended fix: establish a small rule that new watcher state access enters through a DAO or documented engine helper; migrate only touched paths.

## Out of scope

- Provider cost and network policy were covered by the security stage.
- UI usability, detailed business correctness, and live host configuration were not reviewed here.

## Recommended next iterations

- Correct the public architecture and concept documents to one current SQLite/XDG model.
- Decompose the watcher by extracting a single reconciliation concern with an end-to-end race test.
- Add an architecture ratchet that rejects active docs which reference unregistered CLI commands.
