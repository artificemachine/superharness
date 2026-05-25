# Bulletproof Report — "SQLite is Single Source of Truth"
**Date:** 2026-05-25 (v8 — post-ship audit of v1.64.0)
**Focus invariant:** SQLite is **single** source of truth
**Mode:** audit
**Prior baseline:** v7 (claimed 14/14 honest — partially false)

---

## PARTIAL RETRACTION OF v7

v7 claimed 14/14 verified. **Three findings break that.** v1.64.0 was shipped with these gaps:

### Finding 1 (NEW): `list_agent_heartbeats` discards YAML once SQLite is non-empty

`src/superharness/engine/heartbeat_contract.py:222-262`:

```python
rows = watcher_heartbeat_dao.get_all(conn)
if rows:                            # ← if ANY SQLite row exists...
    results = [...]                 # ← ...return ONLY SQLite rows
    return results
# YAML fallback only runs when SQLite is COMPLETELY empty
```

In production: once the watcher writes ANY heartbeat (immediate, every 30 s), SQLite has at least one row. An external agent (Codex CLI, Gemini, OpenCode) that writes `.superharness/agents/<runtime>.heartbeat.yaml` directly — bypassing our `write_heartbeat()` API — is **invisible to `list_agent_heartbeats`**.

This breaks the heartbeat contract v1 promise that external runtimes can drop YAML files and be picked up.

### Finding 2 (NEW): `read_all_agent_statuses` has the same flaw

`src/superharness/engine/agent_status.py:215-247`:

```python
rows = agent_runtime_status_dao.get_all(conn)
...
if rows:
    return {r.runtime: ... for r in rows}    # ← skip YAML scan
```

Same regression: external runtimes writing `agents/<runtime>.status.yaml` directly become invisible as soon as SQLite has any row.

### Finding 3 (NEW): `onboarding.yaml` is YAML-only operational state

`src/superharness/commands/onboard.py:83-98`:

```python
def _load_state(sh: Path) -> dict:
    state_file = sh / "onboarding.yaml"
    if state_file.exists():
        doc = yaml.safe_load(state_file.read_text()) or {}    # ← state read
        ...

def _save_state(sh: Path, state: dict) -> None:
    (sh / "onboarding.yaml").write_text(yaml.dump(state, ...))    # ← state write
```

Operational state (step completion: `pending` / `completed`, config_version for migrations). Read and written as YAML. No SQLite table. The YAML guard's `_STATE_TOKENS` lists `agent-pulse.yaml`, `.heartbeat.yaml`, `.status.yaml` — but **NOT** `onboarding.yaml`. So the guard misses it.

---

## SCOPE

superharness Python CLI. Same as v7 — post v1.64.0 ship audit.

---

## CLAIMS AUDITED

| # | Claim | Verdict | Evidence |
|---|-------|---------|----------|
| C1 | YAML state files dead (contract/inbox/failures/decisions.yaml) | **VERIFIED** | held |
| C2 | reads through DAOs | **VERIFIED** | held |
| C3 | YAML never read as authoritative | **VIOLATED** | `onboard.py:86` reads `onboarding.yaml` as authoritative state with no SQLite alternative. Guard tokens don't include `onboarding.yaml`. |
| C4 | YAML runtime write paths eliminated | **VIOLATED** | `onboard.py:98` writes `onboarding.yaml` unconditionally as the only state store for onboarding progress. Not gated by `is_sqlite_only()` (no SQLite alternative exists). |
| C5 | BASELINE empty | VERIFIED (narrow) | empty but scanner blind spots + token gaps remain |
| C6-C8 | handoffs_fts, yaml_sync_queue, yaml_sync.py | **VERIFIED** | held |
| C9 | watcher heartbeat in SQLite | **VERIFIED (narrow)** | watcher's own heartbeat is in SQLite. BUT external agents' heartbeats via YAML are invisible via `list_agent_heartbeats` once SQLite has any rows. |
| C10 | agent runtime status in SQLite | **VERIFIED (narrow)** | same caveat — external `.status.yaml` invisible via `read_all_agent_statuses` once SQLite is non-empty |
| C11 | agent pulse in SQLite | **VERIFIED** | single-record; mixed-source ambiguity doesn't apply |
| C12 | guard tokens cover heartbeat/status/pulse | **VIOLATED** | Tokens cover those three, but `onboarding.yaml` is missing from `_STATE_TOKENS`. The dishonest "config exclusion" concern reappears in different form: onboarding state slipped through because no one added the token. |
| C13 | inbox DAO completeness | **VERIFIED** | held — 0 raw inbox SQL outside DAO |
| C-LIST | **list_* functions correctly merge SQLite + YAML** | **VIOLATED** | NEW. `list_agent_heartbeats` and `read_all_agent_statuses` return ONLY SQLite when SQLite is non-empty. External runtimes writing YAML directly become invisible. |
| C-MAIN | **"SQLite is SINGLE source of truth"** | **VIOLATED** | onboarding state is YAML-only; external-agent heartbeat/status YAMLs exist as a parallel source that the new SQLite-first logic ignores. Both undermine "single". |

---

## HONESTY SCORE: 9/14 verified. 5 violations. v7's 14/14 was wrong.

**Blunt summary:** Three real bugs shipped in v1.64.0. Two are correctness regressions I introduced (mixed-source list functions); one is a pre-existing gap I missed (onboarding.yaml). The "single" qualifier still doesn't hold.

---

## DRIFT-CLASS FINDINGS

### Correctness regressions introduced in v1.64.0

- **`list_agent_heartbeats`** (heartbeat_contract.py:222) — `if rows: return` short-circuits the YAML scan. Should merge: take SQLite rows, then scan agents/ for YAML files whose agent_id is NOT in the SQLite set. Same fix applies to `read_all_agent_statuses` (agent_status.py:225).

### Unprotected state

- **`onboarding.yaml`** — full operational state cycle in YAML only. No SQLite migration in v25. Either add a `onboarding_state` table + DAO, or accept it as a one-shot setup artifact and document that exception explicitly in the guard.

### Guard incompleteness

- `_STATE_TOKENS` missed `onboarding.yaml` because no one thought to add it. The fundamental risk surfaced in v4 ("definitional exclusion") reappears in passive form: anything we forget to list, the guard ignores. A complementary scan for `.yaml` files under `.superharness/` that aren't in an allowlist would catch new state files at creation time.

### Scanner limitation (unchanged from v6)

AST taint is intra-function only. `pulse_path = _pulse_path(project_dir)` escapes detection. Manual `# noqa: state-read` discipline still needed.

---

## REMEDIATION

### Per-finding patch

1. **`list_agent_heartbeats` merge fix:**
   ```python
   sqlite_results = ...  # build dict {agent_id: AgentHeartbeat}
   # Always scan YAML; SQLite wins for shared keys
   for fname in os.listdir(agents_dir):
       if fname.endswith(".heartbeat.yaml"):
           hb = read_heartbeat(...)
           if hb and hb.agent_id not in sqlite_results:
               sqlite_results[hb.agent_id] = hb
   return list(sqlite_results.values())
   ```

2. **`read_all_agent_statuses` merge fix:** same pattern.

3. **`onboarding.yaml` options (pick one):**
   - Migrate to SQLite: `onboarding_steps(step_name TEXT PK, status TEXT, completed_at TEXT)` table + DAO. Dual-write or full migrate.
   - Accept as one-shot config: add `onboarding.yaml` to a NEW `_CONFIG_ALLOWLIST` in the guard with a justification comment, NOT silent exclusion.

4. **Guard hardening:** add `onboarding.yaml` to `_STATE_TOKENS` if going migrate route; or add the explicit `_CONFIG_ALLOWLIST` mechanism if accepting it as config.

---

## PROGRESS vs v7

| Claim | v7 | v8 |
|-------|-----|-----|
| C3 YAML never auth | VERIFIED | **VIOLATED** (onboarding.yaml) |
| C4 YAML writes eliminated | VERIFIED | **VIOLATED** (onboarding.yaml save) |
| C9/C10 heartbeat/status SQLite | VERIFIED | VERIFIED (narrow — external YAML invisible) |
| C12 guard tokens cover state | VERIFIED | **VIOLATED** (onboarding.yaml missing) |
| C-LIST mixed-source merge | not audited | **VIOLATED** (new finding) |
| C-MAIN single SoT | VERIFIED | **VIOLATED** (regression visibility + onboarding) |

**Net: 14/14 (v7 dishonest) → 9/14 (v8 honest). Three real bugs shipped in v1.64.0.**

---

## WHAT IT WOULD TAKE TO REACH 14/14 HONEST

1. Fix `list_agent_heartbeats` merge logic (~10 lines)
2. Fix `read_all_agent_statuses` merge logic (~10 lines)
3. Decide on onboarding.yaml: migrate to SQLite OR explicit config-allowlist mechanism
4. Add `onboarding.yaml` to `_STATE_TOKENS` (if migrating) OR add `_CONFIG_ALLOWLIST` (if explicit)
5. Write regression tests:
   - `test_list_agent_heartbeats_includes_external_yaml_when_sqlite_has_watcher`
   - `test_read_all_agent_statuses_includes_external_yaml_when_sqlite_has_native`
   - Whatever onboarding test fits the chosen approach
6. Bump 1.64.0 → 1.64.1 (patch)

Estimated patch: 4 files, 1 SQLite migration (if doing onboarding to SQLite), 3 new tests.

---

## REPORT TRAIL

- v4 (claimed 8/8, was 5/8) — definitional exclusion of heartbeat
- v5 (claimed 13/13, was 9/14) — unconditional dual-writes + scanner blind spot
- v6 (correctly identified 5 violations) — minimal patch path documented
- v7 (claimed 14/14 honest) — **MISSED 3 new findings**: list-merge regressions in v5 fixes + onboarding.yaml pre-existing gap
- **v8 (this report):** retracts v7's 14/14. Three patches available.

The pattern: each report finds new violations the previous claimed verified. The discipline only works if the audit hunts ruthlessly each time. Two of the three v8 findings were caused by v5/v7 fixes themselves — every fix is a potential regression vector.
