# Bulletproof Report — 2026-05-24 v2 (Focused: "SQLite is Single Source of Truth")

**SCOPE:** superharness (Python). Focused invariant — "SQLite is single source of truth."
Re-audit after cleanup commit. Probes widened to include handoff YAML layer. Prior report: `bulletproof-report-2026-05-24-sqlite-sot.md`.

---

## CLAIMS AUDITED

| Claim | Source | Verdict | Evidence |
|-------|--------|---------|----------|
| "contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | `CLAUDE.md:9`, `AGENTS.md:31` | **VERIFIED** | Ratchet BASELINE empty. `test_no_state_yaml_reads.py` 3/3 pass. Zero live reads outside migration tools. |
| "YAML files are export-only artifacts; they are never read as authoritative input" | `engine/sqlite_only.py:6` | **VIOLATED** | `discuss.py:90` globs `handoffs/*.yaml` for approval status. `discuss.py:179` reads+writes `approval_gate` to handoff YAML without touching SQLite. `delegate.py:172` globs `handoffs/*.yaml` for task ID. `inbox_watch.py:870` globs `handoffs/*.yaml` for PR URL. |
| "All operational state reads are routed through DAOs / state_reader" | `engine/sqlite_only.py:3` | **VIOLATED** | `discuss.cmd_status:90` reads approval state from handoff YAML glob, not `handoffs_dao`. `inbox_dispatch._claim_next_item:717`: condition `sqlite_primary and target_filter` falls through to YAML path when `target_filter=None` even if `sqlite_primary=True`. |
| "Migration complete as of 2026-05-24. All operational state reads are routed through DAOs." | `engine/sqlite_only.py:3-4` | **VIOLATED** | `discuss._do_approve` writes `approval_gate` to handoff YAML only. After approval, SQLite `handoffs.content` is stale. Dashboard, `status.py`, `contract_today.py` read approval status from stale SQLite content column. No alarm fires. |
| "state_reader always SQLite in production" | `AGENTS.md:63` | **VERIFIED** | `_get_backend()` defaults to `sqlite_only`. All `state_reader` public APIs route to SQLite. |
| "yaml_sync.py deleted" | `engine/yaml_sync.py:5` (former) | **VERIFIED** | File absent. All callers stripped. |

---

## HONESTY SCORE: 3/6 SoT-related claims VERIFIED.

Three violations. The four named dead files are clean. The handoff YAML layer is still read and written as authoritative state in three workflows: approval gate, task identification, PR URL extraction.

---

## VIOLATION MAP

| File | Line(s) | What it reads | Severity |
|------|---------|---------------|----------|
| `engine/discuss.py` | 90 | handoff YAML glob — approval status | HIGH |
| `engine/discuss.py` | 179, 184-191 | handoff YAML write-back — approval_gate never synced to SQLite | CRITICAL |
| `engine/discuss.py` | ~202 | `contract.yaml` read (now returns `{}` — file gone) | MEDIUM |
| `commands/inbox_dispatch.py` | 717 | `inbox.yaml` read when `target_filter=None` in sqlite_only mode | HIGH |
| `commands/delegate.py` | 172 | handoff YAML glob — task identification | MEDIUM |
| `commands/inbox_watch.py` | 870 | handoff YAML glob — PR URL extraction | LOW |

---

## DRIFT-CLASS FINDINGS

**Dead code that looks live:**
- `engine/inbox.py.next_pending` — reads `inbox.yaml` directly. Wired into `inbox_dispatch` no-target-filter branch. `inbox.yaml` was deleted; this branch now silently produces no items rather than an error.

**Silent-success risk:**
- `discuss._do_approve` writes approval_gate to YAML only. `status.py:877`, `contract_today.py:175`, and `dashboard-ui.pending_approvals` all read approval_gate from the SQLite content column. After approval, those readers see stale pre-approval state. No error is raised.

**Unenforced invariants:**
- `test_no_state_yaml_reads.py` ratchet scans only the four named dead files. Handoff YAML reads are not in scope — `discuss.py`, `delegate.py`, `inbox_watch.py` violations are invisible to CI.
- No test asserts "approval_gate is present in SQLite after `_do_approve` runs."

---

## REMEDIATION

**Priority 1 — discuss.py (CRITICAL):**
- `cmd_status`: replace `glob("handoffs/*.yaml")` with `state_reader.get_handoffs()` → check `metadata["approval_gate"]`.
- `_do_approve`: add `write_handoff_to_db(project_dir, handoff_doc)` after updating the dict. Gate the `_atomic_write` YAML write-back with `not is_sqlite_only()` or remove it entirely. Remove the `safe_load(contract_file, dict)` + `_write_contract` call (contract.yaml is gone; the contract update should go through `tasks_dao.update_status`).

**Priority 2 — inbox_dispatch._claim_next_item:717 (HIGH):**
- Change `if ctx.sqlite_primary and ctx.target_filter:` to `if ctx.sqlite_primary:` and provide a SQLite path for the no-filter case.

**Priority 3 — delegate.py + inbox_watch.py (MEDIUM/LOW):**
- `_get_latest_handoff_task`: replace filesystem glob with `handoffs_dao.get_latest()` filtered by `to_agent`.
- `_find_pr_url_in_handoff`: replace filesystem glob with `handoffs_dao.search(task_id)` regex over `content` column.

**CI guard — extend ratchet:**
Add handoff YAML read patterns to `test_no_state_yaml_reads.py` so `glob("handoffs/*.yaml")` + `safe_load(handoff_file)` fail CI.

---

## PROGRESS (vs 2026-05-24 first focused report)

| Claim | v1 (2026-05-24) | v2 (2026-05-24 re-audit) | Movement |
|-------|-----------------|--------------------------|----------|
| "4 dead files DEAD" | VERIFIED | VERIFIED | held |
| "YAML files export-only" | VERIFIED | **VIOLATED** | scope widened — handoff layer now probed |
| "all reads through DAOs" | VERIFIED | **VIOLATED** | discuss.py + inbox_dispatch found |
| "migration complete" | VERIFIED | **VIOLATED** | approval workflow uses YAML as write SoT |
| "state_reader always SQLite" | VERIFIED | VERIFIED | held |
| "yaml_sync.py deleted" | VERIFIED | VERIFIED | held |

**Net: 3 claims regressed from VERIFIED to VIOLATED when probe scope was widened to include handoff YAML. The prior "VERIFIED" verdicts were correct for their narrow probe scope; the ratchet blind spot is the root cause.**
