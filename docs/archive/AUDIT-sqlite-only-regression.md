# SQLite-Only Source Of Truth Regression

> **STATUS: FIXED (2026-05-05)** — All 5 vectors resolved + 1 additional write-path fix.
> YAML is now export-only. SQLite is the sole runtime data path.
> See `docs/IMPLEMENTATION-status.md` for full status.

The project policy says runtime state should come from SQLite only:

`.superharness/state.sqlite3` is canonical. `contract.yaml`, `inbox.yaml`, and related YAML files are not supposed to drive behavior anymore, except as exported snapshots or compatibility artifacts.

The original code weakened that contract in several places:

1. ~~[`state_reader.py`](../src/superharness/engine/state_reader.py) chooses a backend and defaults to `"dual"`~~ → **FIXED**: defaults to `sqlite_only`

2. ~~[`state_reader.py`](../src/superharness/engine/state_reader.py) calls `_ensure_ingested()` before reads~~ → **FIXED**: removed from all production paths

3. ~~[`state_reader.py`](../src/superharness/engine/state_reader.py) falls back to `_tasks_from_yaml()` silently~~ → **FIXED**: raises in sqlite_only mode, YAML fallback only in dual mode

4. ~~[`sqlite_only.py`](../src/superharness/engine/sqlite_only.py) returns true only when `STATE_BACKEND=sqlite_only`~~ → **FIXED**: this is the default

5. ~~[`yaml_sync.py`](../src/superharness/engine/yaml_sync.py) reintroduces YAML sync/writeback~~ → **FIXED**: stripped to 30-line no-op stubs

6. ~~`_export_contract_yaml` / `_export_inbox_yaml` wrote YAML on every status change~~ → **FIXED**: no-op in sqlite_only mode

7. ~~Dashboard discussion count read from filesystem~~ → **FIXED**: reads from SQLite discussions_dao

8. ~~`shux task create` wrote to YAML only~~ → **FIXED**: writes to SQLite directly

**Result**: No YAML reads or writes in production. YAML is generated only on explicit `shux export-yaml`. 151 tests enforce this at CI time.

## Original vectors (historical)

1. `state_reader.py` chose a backend and defaulted to `"dual"`. Normal runtime was not clearly SQLite-only.
2. `_ensure_ingested()` re-migrated stale YAML into SQLite on every read.
3. YAML fallback on SQLite errors silently masked real DB failures.
4. `sqlite_only.py` was opt-in instead of default.
5. `yaml_sync.py` had active sync/writeback behavior despite being deprecated.

All 5 vectors + 3 additional write-path issues are now closed.
