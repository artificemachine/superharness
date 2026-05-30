# Bulletproof Report — 2026-05-29 (general audit, v13)

SCOPE: Repo-wide claim audit (Python, 227 src + 389 test files). Doctrine: CLAUDE.md, AGENTS.md, docs/ARCHITECTURE.md, module docstrings. First *general* run since the v2–v12 series (which focused narrowly on SQLite-SoT durability). Ran the existing enforcement guards and harvested claims across all doctrine.

## HEADLINE

The **code** invariants hold — every one is backed by a passing guard test. The **violations are all documentation drift**: three doctrine/docstring claims describe a pre-SQLite world or name files that no longer exist. The code is honest; some docs lie about the code.

## CLAIMS AUDITED

| Claim | Source | Verdict | Evidence |
|-------|--------|---------|----------|
| "State lives in SQLite — contract/inbox/failures/decisions YAML are DEAD" | CLAUDE.md:9, AGENTS.md:31 | **VERIFIED** | `tests/test_no_state_yaml_reads.py` passes (3 tests). Remaining `yaml.safe_load` calls are config/profile/boundary/crash-dump reads, all `# noqa: state-read` justified. Dashboard `contract_tasks`/`inbox_items` route through `state_reader` (SQLite); `read_contract` reconstructs from SQLite in sqlite_only mode (default). |
| "Single source of truth for flagship model" | test_flagship_source_of_truth.py (today) | **VERIFIED** | Guard test passes 5/5; no `claude-opus-4-N` literal outside approved files. |
| "Every YAML classified; new YAML fails CI" | state_manifest.yaml, AGENTS.md | **VERIFIED** | `tests/test_yaml_manifest_complete.py` passes (5 tests). |
| "C-DURABLE-READ: fresher of SQLite vs YAML crash-dump wins" | bulletproof v12 manifest | **VERIFIED** | `onboard.py:90-126` retains mtime comparison; `state_reader.py` unchanged since v12 (empty git log since 2026-05-25). "No silent YAML fallback" in `get_tasks` is about *normal* reads, not crash recovery — not a contradiction. |
| "CHANGELOG is append-only" | CLAUDE.md:11, AGENTS.md:78 | **VERIFIED** | Enforced by `.github/workflows/tests.yml:19` + `scripts/check-changelog-append-only.sh` + global pre-commit hook. |
| "Cross-repo branch convention RETIRED" | CLAUDE.md:94 | **VERIFIED** | No live `feat/superharness-integration-morpheme` refs in src; morpheme appears only as a documented consumer. |
| **"contract.yaml — the source of truth"** | docs/ARCHITECTURE.md:61, :25 | **VIOLATED** | ARCHITECTURE.md has **zero** mention of SQLite; describes `contract.yaml`/`decisions.yaml`/`failures.yaml` as live SoT. Directly contradicts the enforced SQLite-SoT invariant. Stale since commit `b062477` (pre-migration). |
| **"All contract-mutating commands must use write_contract()"** | engine/contract_io.py:3 | **VIOLATED** | 6 files call `write_contract`; **15** mutate via `tasks_dao` directly, plus raw SQL `UPDATE/INSERT/DELETE tasks` in `mcp/tools/contract.py`, `dashboard-ui.py:1890,3087`, `task.py:275`, `inbox_watch.py` (×8), `discussion_dispatch.py:257`, `discuss.py:292`. The DAO is the real mutation layer; the docstring overclaims. No test enforces it. |
| **"Modules exist as no-op stubs (parity.py, yaml_sync.py, heal_parity.py)"** | AGENTS.md:48 | **VIOLATED** | `yaml_sync.py` and `heal_parity.py` **do not exist** (`ls` → No such file). Only `parity.py` exists (a genuine no-op stub). 2 of 3 named modules are absent; `heal_parity` is a *function* in parity.py, not a module. |
| "state_reader read API (always SQLite)" | AGENTS.md:63 | **VIOLATED** (precision) | Literally false: `yaml_only` mode (`state_reader.py:6`) reads YAML and ignores SQLite. It is a documented emergency-rollback override, not the default (default = sqlite_only). Low severity — the word "always" is the only defect. |
| "Never merge to main without owner approval" | CLAUDE.md:12, AGENTS.md:34 | **UNCHECKABLE** | Depends on GitHub branch-protection settings (not in repo) + human discipline. No static probe. Flag for human: confirm branch protection is actually configured on `celstnblacc/superharness`. |

## HONESTY SCORE: 6/10 checkable completion-claims true.

**Blunt summary:** Every code invariant is real and guard-enforced. All 4 violations are documentation that drifted away from correct code — `ARCHITECTURE.md` still describes the pre-SQLite world, two named "stub modules" were deleted, and one docstring claims a write-path discipline the codebase abandoned for a DAO layer. Nothing is *functionally* broken; the docs are lying about a system that is actually fine.

## DRIFT-CLASS FINDINGS

- **Dead code that looks live:** `engine/parity.py` (no-op stub) has **zero importers** in src — it can be deleted now (its own docstring says "Will be deleted entirely in Phase 4"). `yaml_sync.py`/`heal_parity.py` already gone but still named in AGENTS.md.
- **Silent-success risk:** None new. `state_reader.get_tasks` correctly fails loud on SQLite error (raises, no silent `[]`).
- **Unenforced invariant:** `contract_io.py` docstring "all contract-mutating commands must use write_contract()" has no enforcing test and is bypassed 15:6. Either the docstring is wrong (likely) or the rule needs a guard.

## REMEDIATION

**Manifest (per claim, required booleans):**
```
DOC-ARCH:   ARCHITECTURE.md mentions SQLite as SoT          [ ] (currently absent)
DOC-ARCH:   ARCHITECTURE.md does not call contract.yaml SoT  [ ]
DOC-WRITE:  contract_io docstring matches actual write paths [ ]
DOC-STUB:   AGENTS.md names only modules that exist          [ ] (yaml_sync/heal_parity absent)
DOC-ALWAYS: "always SQLite" softened to "SQLite by default"  [ ]
CODE-SOT:   no-state-yaml-reads guard passes                 [x]
CODE-FLAG:  flagship-source-of-truth guard passes            [x]
CODE-MANIFEST: yaml-manifest-complete guard passes           [x]
```

**Fixes (doc-only, no code change needed):**
1. Rewrite `docs/ARCHITECTURE.md` "Runtime State" section to name SQLite as SoT, or add a legacy banner pointing to AGENTS.md.
2. Correct `engine/contract_io.py:3` docstring: `write_contract()` is the full-document path; `tasks_dao` is the row-level mutation DAO.
3. Update `AGENTS.md:48` — drop `yaml_sync.py`/`heal_parity.py`; note only `parity.py` remains (or delete it for Phase 4 and drop the line entirely).
4. Soften `AGENTS.md:63` "always SQLite" → "SQLite by default; `yaml_only` is an emergency override".

**Guard (not written — audit mode):** a doc-drift guard could assert (a) every module named in AGENTS.md exists, and (b) ARCHITECTURE.md does not contain "contract.yaml ... source of truth". Re-run with `--emit-guard` to write it.

## PROGRESS (vs v12, 2026-05-25)

| | v12 | v13 |
|---|---|---|
| Focus | SQLite-SoT durability (narrow) | repo-wide general audit |
| SQLite SoT code invariants | 15/15 | **all held** (re-verified via guards) |
| New invariant: flagship SoT | — | **VERIFIED + enforced** (shipped today, v1.69.1) |
| New finding class | — | **documentation drift** (4 violations, all docs) |

v12 proved the code; v13 finds the docs describing it have rotted. The guards added across v2–v12 are doing their job — every code claim they cover is honest. The gap is doctrine no one wired a guard around: prose in ARCHITECTURE.md, AGENTS.md, and a docstring.

---

## REMEDIATION APPLIED (2026-05-29, same session)

All four doc-drift violations fixed, plus a durable guard so the class can't recur:

| Violation | Fix |
|-----------|-----|
| ARCHITECTURE.md "contract.yaml is the source of truth" | Added pre-SQLite legacy banner; rewrote Runtime State block (state.db = SoT; YAMLs = tombstone exports) |
| contract_io.py docstring "all mutations must use write_contract()" | Corrected: write_contract = full-document path; tasks_dao = row-level; state_writer = status |
| AGENTS.md names deleted stub modules | Reworded: only parity.py remains (zero callers, pending Phase-4) |
| AGENTS.md "state_reader always SQLite" | Softened: "SQLite by default; yaml_only is an emergency override" |

**Guard added:** `tests/test_doc_drift.py` (2 probes — named-entity existence + state-YAML SoT consistency). RED→GREEN verified; mutation-check passed (injected violation tripped both probes, revert restored green). Runs in the default `pytest tests/` collection, so CI now enforces it on every PR.

**Honesty score after remediation: 10/10 checkable completion-claims true** (the 11th, "never merge to main without owner approval", remains UNCHECKABLE — depends on GitHub branch protection).

**Tool patch:** the doc-drift class, remediation-follow-through step, coverage ledger, and "doc claims get guards too" rule were added to the global `/bulletproof` command (project-agnostic) so future audits catch this class everywhere, not just here.
