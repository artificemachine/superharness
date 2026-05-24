# Bulletproof Report — "SQLite is Single Source of Truth"
**Date:** 2026-05-24 (v6 — post v5, ruthless audit)
**Focus invariant:** SQLite is **single** source of truth
**Mode:** audit
**Prior baseline:** v5 (claimed 13/13 — partially honest, see retraction below)

---

## PARTIAL RETRACTION OF v5

v5 claimed 13/13 VERIFIED. Two findings break that:

1. **Scanner blind spot.** `commands/agent_pulse.py:118` reads `agent-pulse.yaml` via `pulse_path.read_text()` with no `# noqa: state-read`. The YAML guard PASSED anyway. Why? The AST scanner can't trace `pulse_path = _pulse_path(project_dir)` through the function call to detect taint. The new tokens were correct; the scanner taint analysis is intra-function only.

2. **Unconditional YAML writes.** All three dual-write paths write YAML on every state change, with NO `is_sqlite_only()` gate:
   - `engine/heartbeat_contract.py:123` — writes `watcher.heartbeat.yaml` every heartbeat
   - `engine/agent_status.py:131` — writes `agents/<runtime>.status.yaml` every status update
   - `commands/agent_pulse.py:81` — writes `agent-pulse.yaml` every pulse

   Compare `engine/state_writer.py:222-223` (`if not is_sqlite_only(): _export_inbox_yaml(project_dir)`) — this is the correct pattern. The new dual-writes did not adopt it.

The word "single" in the invariant means "one". When state is actively maintained in two stores simultaneously, the invariant is VIOLATED — even if reads prefer one.

---

## SCOPE

Python multi-agent session handoff CLI (`superharness`). Source under
`src/superharness/`. Doctrine in `CLAUDE.md`, `AGENTS.md`,
`src/superharness/engine/sqlite_only.py`, `IMPLEMENTATION-status.md`.
Guard: `tests/test_no_state_yaml_reads.py`.

---

## CLAIMS AUDITED

| # | Claim | Source | Verdict | Evidence |
|---|-------|--------|---------|----------|
| C1 | "contract.yaml, inbox.yaml, failures.yaml, decisions.yaml are DEAD" | CLAUDE.md:9 | **VERIFIED** | Those 4 files specifically — gone. `contract_io.py:237–243` gates the YAML path behind `is_sqlite_only()`. |
| C2 | "All operational state reads routed through DAOs / state_reader" | `sqlite_only.py:3` | **VERIFIED** | All reads go through DAOs. `discussions_dao.register_yaml_submission` is the ingest boundary. |
| C3 | "YAML files never read as authoritative input" | `sqlite_only.py:6` | **VIOLATED** | `commands/agent_pulse.py:118` reads agent-pulse.yaml without `# noqa: state-read`. The guard misses it (intra-function taint limitation). Also `engine/discussions_dao.py:162` returns `os.path.isfile(yaml_path)` as proof of submission — YAML existence as authoritative state during race window. |
| C4 | "All YAML runtime read/write paths eliminated" | `IMPLEMENTATION-status.md:60` | **VIOLATED** | YAML **write** paths are NOT eliminated. Three dual-write sites unconditionally write YAML: `heartbeat_contract.py:123`, `agent_status.py:131`, `agent_pulse.py:81`. None are gated by `is_sqlite_only()`. |
| C5 | "ratchet guard BASELINE is empty" | `tests/test_no_state_yaml_reads.py:4` | **VERIFIED (narrow)** | `BASELINE = set()` confirmed. But guard has scanner blind spots (intra-function taint only). An "empty BASELINE" passing CI is not the same as "no violations exist". |
| C6 | "handoffs_fts dead" | prior plan | **VERIFIED** | Migration v23. |
| C7 | "yaml_sync_queue dropped" | prior plan | **VERIFIED** | Migration v24. |
| C8 | "yaml_sync.py deleted" | prior plan | **VERIFIED** | File absent. |
| C9 | "watcher heartbeat is in SQLite" | v5 | **VERIFIED (narrow)** | Migration v25 + `read_heartbeat_db` + `operator.py` SQLite-first reads. Data IS in SQLite. BUT not the SAME as "ONLY in SQLite" — see C4. |
| C10 | "agent runtime status is in SQLite" | v5 | **VERIFIED (narrow)** | Same as C9. `agent_runtime_status` table + DAO + SQLite-first reads. Dual-write to YAML continues. |
| C11 | "agent pulse is in SQLite" | v5 | **VERIFIED (narrow)** | Same as C9. PLUS the scanner blind spot at `agent_pulse.py:118` means the read fallback is unguarded. |
| C12 | "YAML guard tokens cover heartbeat/status/pulse" | v5 | **VERIFIED (token list)** | Tokens are listed in `_STATE_TOKENS`. BUT the AST taint scanner is intra-function only — paths constructed via helper functions (`pulse_path = _pulse_path(project_dir)`) escape detection. Guard is incomplete, not broken. |
| C13 | "all inbox mutations through inbox_dao" | v5 | **VERIFIED** | Zero raw `conn.execute.*UPDATE/INSERT/DELETE inbox` outside `inbox_dao.py`. 7 new DAO functions cover all needs. |
| C-MAIN | **"SQLite is SINGLE source of truth"** | CLAUDE.md, sqlite_only.py | **VIOLATED** | "Single" means one. State is actively maintained in TWO stores (SQLite + YAML) for heartbeat, agent_status, agent_pulse. Dual-writes are unconditional. A pedant reads "single" as "exclusive"; the code maintains two parallel stores. |

---

## HONESTY SCORE: 9/14 verified. 5 violated (C3, C4, C-MAIN; C5/C12 verified-but-incomplete).

**Blunt summary:** SQLite is the read-priority source. It is not the SINGLE source. YAML is still actively maintained as a parallel store on every state change. v5 was correct that data is in SQLite. v5 was wrong that this makes SQLite the single source of truth.

---

## DRIFT-CLASS FINDINGS

### Unguarded YAML read (scanner blind spot)

- `commands/agent_pulse.py:118` — `yaml.safe_load(pulse_path.read_text(...))`. `pulse_path` is built by `_pulse_path(project_dir)` (returns Path with `agent-pulse.yaml`). The AST scanner doesn't follow the call. **Fix options:**
  - Add `# noqa: state-read — YAML fallback when SQLite empty (legacy projects)` to line 118
  - Inline `_pulse_path` so the scanner sees the path construction
  - Improve scanner: trust function names matching `_*_path` or use a name-based heuristic

### Unconditional dual-writes (parallel store, not export mirror)

Three writers create YAML unconditionally — there is no opt-out. The watcher process writing 30-second heartbeats produces a constant stream of YAML writes alongside SQLite writes:

- `engine/heartbeat_contract.py:91-123` — writes `.superharness/watcher.heartbeat.yaml` and per-agent `.heartbeat.yaml` files
- `engine/agent_status.py:128-131` — writes `.superharness/agents/<runtime>.status.yaml`
- `commands/agent_pulse.py:75-81` — writes `.superharness/agent-pulse.yaml`

**Fix pattern (from `state_writer._export_inbox_yaml`):**
```python
from superharness.engine.sqlite_only import is_sqlite_only
if is_sqlite_only():
    return  # SQLite is SoT — YAML is not maintained at runtime
```

Apply this to gate the YAML write in each of the 3 dual-writers. Then `shux export-yaml` (if it exists) becomes the only way to materialize YAML mirrors.

### Discussion submission YAML-as-existence-check

`engine/discussions_dao.py:160-162`:
```python
if discussion_dir is not None:
    yaml_path = os.path.join(discussion_dir, f"round-{round_}-{agent}.yaml")
    return os.path.isfile(yaml_path)
```

This treats YAML existence as authoritative "agent has submitted". The docstring acknowledges it's an "evidence-of-work fallback" for race-window resilience. For strict SoT, the call site should always invoke `register_yaml_submission` before checking SQLite (synchronous ingest), then check SQLite only. Currently the race-window optimization makes YAML a transient state signal.

Status: minor violation, intentional design. Document or remove.

### Scanner limitation (guard incomplete, not broken)

The AST taint scanner only tracks variable assignments within a single function. Path-building helpers escape detection:

```python
pulse_path = _pulse_path(project_dir)   # scanner doesn't know _pulse_path returns a state path
data = yaml.safe_load(pulse_path.read_text())  # missed by scanner
```

**Mitigations (pick one):**
- Add explicit `# noqa: state-read` at all known fallback sites (manual discipline)
- Add a complementary regex scanner that catches `read_text\|read_bytes\|readlines` on any variable whose NAME contains a state token (pulse_path, heartbeat_path, status_path, handoff_path)
- Inline the helpers at the call sites (lose the abstraction but gain the check)

---

## REMEDIATION

### Per-claim manifest (what must hold for VERIFIED)

```
C3 "YAML never read as authoritative":
  [ ] agent_pulse.py:118 has # noqa: state-read   OR  is removed
  [ ] discussions_dao._already_submitted YAML fallback removed OR justified

C4 "All YAML runtime write paths eliminated":
  [ ] heartbeat_contract.write_heartbeat YAML write gated by is_sqlite_only()
  [ ] agent_status.write_agent_status YAML write gated by is_sqlite_only()
  [ ] agent_pulse._write_pulse YAML write gated by is_sqlite_only()

C5 "BASELINE empty AND scanner has no blind spots":
  [ ] Scanner catches function-call path construction (e.g. name-based heuristic)
  [ ] OR baseline includes the known blind spots
```

### Recommended guards

1. **Cross-function path-name heuristic:** flag any `.read_text|.read_bytes|.readlines` call on a variable whose name matches `*_path|*_file|*_yaml` if the variable was assigned from a function call returning a path. Manual implementation needed.
2. **Write-side guard:** mirror of the read guard. Scan for `yaml.dump|yaml.safe_dump` on state paths without `is_sqlite_only()` gate or `# noqa: state-write` justification.

---

## PROGRESS (vs v5)

| Claim | v5 verdict | v6 verdict | Why changed |
|-------|-----------|-----------|-------------|
| C1-C2 | VERIFIED | VERIFIED | held |
| C3 YAML never auth | VERIFIED | **VIOLATED** | scanner blind spot at agent_pulse.py:118 + discussion existence check |
| C4 YAML write paths eliminated | VERIFIED | **VIOLATED** | 3 unconditional dual-write sites discovered |
| C5 BASELINE empty | VERIFIED | VERIFIED (narrow) | technically empty but scanner has known blind spots |
| C6-C8 | VERIFIED | VERIFIED | held |
| C9-C11 | VERIFIED | VERIFIED (narrow) | data IS in SQLite, but also in YAML |
| C12 guard tokens cover | VERIFIED | VERIFIED (token list) | tokens correct, scanner taint analysis limited |
| C13 inbox DAO complete | VERIFIED | VERIFIED | held |
| C-MAIN "SQLite is SINGLE SoT" | (implicit VERIFIED) | **VIOLATED** | "single" requires exclusivity; system maintains two parallel stores |

**Net: 13/13 (v5 dishonest) → 9/14 (v6 honest, after counting C-MAIN explicitly). 5 violations remain.**

---

## WHAT IT WOULD TAKE TO MAKE C-MAIN TRUE

To make "SQLite is single source of truth" actually true:

1. Gate the 3 dual-write YAML calls behind `is_sqlite_only()` (small patch)
2. Add `# noqa: state-read` to the agent_pulse.py:118 fallback (one line)
3. Either remove `discussions_dao._already_submitted` YAML existence fallback OR re-frame the claim to acknowledge race-window ingest
4. Improve the scanner to follow function-call path construction (medium patch)
5. Delete the .superharness/{watcher.heartbeat.yaml, agents/, agent-pulse.yaml} files from existing projects (or leave as legacy artifacts — they'll go stale)

After (1) and (2), C3, C4, C-MAIN flip to VERIFIED. After (4), C5 flips from "narrow" to "broad". That gets to 13/13 honest.

---

## REPORT TRAIL

- v2 (2026-05-24): baseline audit, scope was reads only
- v3 (2026-05-24): added C4-C7-C8, surfaced inbox_dispatch fallback + yaml_sync_queue
- v4 (2026-05-24): claimed 8/8 — definitional sleight-of-hand (excluded heartbeat as "config")
- v5 (2026-05-24): retracted v4, migrated heartbeat/status/pulse to SQLite reads, claimed 13/13
- **v6 (this report):** retracts v5's "single SoT" claim — dual-writes mean two parallel stores, not single SoT
