# Bulletproof Report — 2026-05-22

**SCOPE:** superharness (Python). Focus invariant: **"SQLite is source of truth"**. Doctrine in `engine/sqlite_only.py` + `CLAUDE.md`. Audit mode (read-only).

## CLAIMS AUDITED

| Claim | Source | Verdict | Evidence |
|-------|--------|---------|----------|
| "The YAML→SQLite migration is complete." | `engine/sqlite_only.py:3` | **VIOLATED** | handoffs + ledger never moved (rows below) |
| "All state lives in SQLite." | `engine/sqlite_only.py:3` | **VIOLATED** | handoffs are written YAML-only; `handoffs` table populated only by migration |
| "YAML files are no longer read or written for operational purposes." | `engine/sqlite_only.py:4` | **VIOLATED** | operational YAML **writes**: `engine/state_writer.py:272`, `commands/handoff_write.py:255`, `mcp/tools/handoffs.py:44`. operational YAML/`.md` **reads**: `engine/recall.py:71,143`, `commands/task.py:357,359`, `commands/context.py:288`, `mcp/tools/ledger.py:17` |
| "contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | `CLAUDE.md:9` | **VERIFIED** (for those four) | tasks/inbox go through SQLite; the listed files are not read operationally. NB: the claim conspicuously omits **handoffs** and **ledger** — which are the live offenders |

## HONESTY SCORE: 1/4 completion-claims true.

The doctrine asserts a finished migration. It is not finished: **handoffs and ledger are still operationally YAML.** The narrow CLAUDE.md claim (four named files dead) is technically true precisely because it omits the two entities that aren't.

## DRIFT-CLASS FINDINGS

- **No writer puts handoffs in SQLite.** The three operational handoff writers all emit YAML and none call `handoffs_dao.append`:
  - `engine/state_writer.py:272` → writes `handoffs/{id}.yaml`
  - `commands/handoff_write.py:255` → `target.write_text(yaml.safe_dump(...))`
  - `mcp/tools/handoffs.py:44` → `f"{task_id}-{phase}-{ts}-mcp.yaml"`
  `handoffs_dao` is referenced only by `commands/yaml_io.py` (migration/import), `engine/state_reader.py`, `engine/observation_capture.py` — never by an operational writer. So the `handoffs` table is empty/stale in practice.
- **Silent-success risk (the reason this hid):** readers glob the YAML exports and get correct-looking data — `engine/recall.py:71` (`handoffs_dir.glob("*.yaml/.yml/.md")`), `engine/recall.py:143` (`ledger.md`), `commands/task.py:357,359`, `commands/context.py:288`, `mcp/tools/ledger.py`. Reading the export is *accidentally correct* for handoffs because the export is the only copy.
- **Dead code that looks live:** `handoffs_fts` appears exactly once (`engine/db.py`, migration v6 CREATE) — never written, never queried; and it declares columns (`agent`, `summary`) that don't exist in the `handoffs` table. `yaml_sync_queue` + `engine/yaml_sync.py` are inert (no-op stubs).
- **Unenforced invariant:** there is NO test that fails when code reads `.superharness/handoffs/*.yaml` or `ledger.md`. The doctrine is prose with zero enforcement — which is why it drifted undetected.

## REMEDIATION

- **Manifest** (per entity → required booleans `{writer_uses_db, reader_uses_db, no_yaml_reader}`):
  - tasks: ✓ ✓ ✓ — DONE
  - inbox: ✓ ✓ ✓ — DONE
  - decisions: ✓ ✓ ✓ (writer/reader exist; recall doesn't surface them — separate feature)
  - failures: ✓ ✓ ✓ (same caveat)
  - discussions: ✓ ✓ ✗ (readers still glob round/state YAML)
  - **ledger: ✓ ✗ ✗** (DAO exists; `state_reader.get_ledger_entries` still merges `ledger.md`; readers glob it)
  - **handoffs: ✗ ✗ ✗** — the keystone failure
- **Guard to add** (`--emit-guard` to generate): a test that greps `commands/ engine/ mcp/ scripts/` for `.superharness/handoffs` globs, `ledger.md` reads, and `contract.yaml`/`inbox.yaml` reads outside an allowlist (export writers + config readers + the discussion ingest bridge), and fails on any hit. Not yet emitted (audit mode).

## GUARD EMITTED (--emit-guard --mutation-check)

`tests/test_no_state_yaml_reads.py` — a ratcheting guard (3 tests, green). Baselines known offenders, fails CI on any new state-YAML read, and forces the baseline to shrink (a baselined file that no longer offends fails until removed). Migration is provably complete only when the baseline is empty.

**Mutation check caught a flaw in the guard itself:** the first version missed the literal-dir form `(p / "handoffs").glob(...)` (matched only the variable form `handoffs_dir.glob`). Fixed with a local-window pattern; re-validated — the guard now fails on the injected violation.

**Guard found a violation both audits missed:** `commands/inbox_watch.py:573` — `glob.glob()` over the handoff dir. Neither the manual pass nor the dedicated audit subagent flagged it. Added to baseline.

**Regex blind spots (declared, not hidden):** helper-indirection (`d = _handoffs_dir(p); os.listdir(d)`) evades regex. 4 real violations invisible to the regex guard: `mcp/tools/handoffs.py`, `mcp/tools/ledger.py`, `commands/contract_today.py`, `commands/delegate.py`. Addressed by the AST upgrade (below).

Calibrated baseline (regex): 7 detected — `adapter_payload.py`, `context.py`, `inbox_watch.py`, `recap.py`, `task.py`, `recall.py`, `dashboard-ui.py`.

## AST UPGRADE (closes the blind spots)

The regex guard was upgraded with intra-file **taint analysis** (`ast`): it identifies helper functions that build a state path (e.g. `_handoffs_dir`, `_ledger_path`), taints variables assigned from them, and flags reads on those vars. This follows the indirection regex cannot.

- **Former blind spots now caught:** `mcp/tools/handoffs.py` (`os.listdir(_handoffs_dir(...))`), `mcp/tools/ledger.py` (`open(_ledger_path(...))`), `contract_today.py`, `delegate.py`. `_KNOWN_BLIND` is now **empty** — no known false negatives.
- **Two AST flaws caught during build (mutation-driven):** (1) `open()` detection initially flagged *writes* (`open(path, "a")`) — fixed to honor the mode; (2) re-validated against a helper-indirection mutation, which it now catches.
- **Final detection: 15 offending files** — nearly double the manual audit's ~8. AST found real reads in `status.py`, `state_reader.py` (the ledger.md merge), `validate.py`, `inbox_watch.py` (3 more sites) that no human pass listed. Two are borderline (`delegate.py:967` reads a `-instructions.md` that lives in the handoffs dir; `init_project.py:524` edits the scaffold) — baselined as YAML-layout coupling.
- **Mutation-tested for both forms:** literal-dir glob AND helper-indirection. Guard is 3 tests, green, ~0.9s.

**Tally: machine 15, humans 8.** The AST guard out-detected two careful manual audits and a regex pass.

## PROGRESS (baseline)

First bulletproof run on this repo. ~19 reader sites + 3 YAML-only writer paths + 4 dead-code items. Guard now mechanically tracks the count. Cross-reference: `PLAN-sqlite-source-of-truth-refactor.md`.
