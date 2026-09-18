# BUG 2026-09-18 — every project path ever seen gets a 340 KB empty `state.db`, and nothing ever prunes it

**Severity:** medium — not a correctness defect and it loses no data by itself, but it grows without bound, and a naive cleanup **will** destroy real state: 112 of 3,372 archived databases contained rows.
**Status:** open. Measured 2026-09-18 on macOS. The 22,485 directories were archived and pruned by hand; the defect itself is unfixed.

## Summary

`resolve_xdg_state_db_path()` (`src/superharness/utils/paths.py`) maps a project directory to
`<state-dir>/<12-char-hash>/state.db`, where the hash is `sha256(abspath(project_path))[:12]`
(`project_hash()`, same file). State precedence is
`SUPERHARNESS_STATE_DIR > XDG_STATE_HOME/superharness > ~/.local/state/superharness`.

Every distinct **absolute path** that any `shux` command touches therefore gets its own directory
and its own fully created database, whether or not a single row is ever written. Nothing reuses
those directories, nothing removes them when a project is deleted, and `shux state` exposes no
prune or GC. On this machine the directory reached **22,485 entries (~7.5 Gi) in about two
months** — roughly 300 new directories per day.

## Evidence (measured 2026-09-18)

Size distribution across the 19,104 databases that were still present after the archive step:

| size (bytes) | count |
|---|---|
| 348,160 | 17,895 |
| 319,488 | 1,123 |
| 339,968 | 68 |
| anything else | ~18 |

The three recurring sizes are the schema freshly created, before any content is written.

Content: a 40-database sample taken at even intervals across the whole set returned **zero rows**
across `handoffs`, `ledger`, `events`, `decisions`, `failures`, `inbox` and `operator_memory`. The
same check on the 3,372 databases older than 30 days found **112 that did hold rows** (between 1
and 93 each), which is why they were archived rather than deleted.

Where the databases come from: the largest surviving one (7.4 Mi) has `project_meta` rows
`id|test-contract`, `goal|Test goal` and holds 1,715 `inbox` and 1,395 `review_store` rows — a
database left behind by a test fixture, not by a real project. This is the dominant source, and it
matches the growth: a test that renders a project into a fresh `tmp_path` creates a project path
that has never been seen before, so each test run adds another 340 KB directory forever.

An empty skeleton cannot be mapped back to its project: `project_meta` is empty in every one of
them, and the directory name is a one-way hash of a path nobody recorded.

## Reproduction

```bash
# How many, how big, how old
S=~/.local/state/superharness
find "$S" -maxdepth 1 -type d | wc -l
du -sh "$S"

# The skeletons: identical size, no content
find "$S" -name state.db -exec stat -f '%z' {} + | sort | uniq -c | sort -rn | head
sqlite3 "$S/<12-hex>/state.db" \
  "select (select count(*) from handoffs)+(select count(*) from ledger)+(select count(*) from events);"

# The growth: run the suite once, then count again
python -m pytest -q
find "$S" -maxdepth 1 -type d | wc -l
```

## Impact

- Unbounded disk growth in a directory the user never looks at: 7.5 Gi here, ~300 entries per day,
  with no ceiling and no warning.
- 22k directories of one file each also degrade backups, `du`, and every tool that walks state.
- Cleanup by hand is unsafe by construction — the hash is irreversible and the skeletons carry no
  project name, so the only safe test is opening every database and counting rows, which is what
  had to be done here. A deletion based on age alone would have destroyed the 112 databases that
  held content.
- On a machine with several agent sessions, every session's working directories and every worktree
  are distinct paths, so the count grows with agent activity, not only with real projects.

## Proposed fix, in order of value

1. **Do not create the database until the first write.** Most of the 22,485 directories never held
   a row; a lazy `connect` that only creates the file on first insert removes the entire skeleton
   class and costs nothing.
2. **`shux state gc`** with `--dry-run`, removing state directories whose tables are all empty and
   whose files have not been touched for N days (default 30), reporting counts and sizes before it
   acts, and never removing one that holds rows.
3. **Record the project path and the last-used timestamp** inside the database, so a directory can
   be mapped back to its project by a human or by the GC. Today `project_meta` holds `id` and
   `goal` for real projects and nothing at all for skeletons.
4. **Stop the test suite from leaking state**: the precedence already supports
   `SUPERHARNESS_STATE_DIR`, so the fixtures can point it at a per-run temporary directory that is
   deleted at the end. This alone should remove most of the daily growth.
5. **Collapse ephemeral paths**: worktrees set `SUPERHARNESS_STATE_PROJECT` for dispatch, but a
   plain `tmp_path` during a test does not, so each one is hashed as if it were a project.

## Notes for whoever fixes this

- Artifacts from the cleanup are on the reporting machine, not in this repository: the archived
  older databases live in `~/.local/state/superharness-archive/superharness-state-older-than-30d-20260918T170523Z.tar.gz`
  (29 Mi compressed) and restore with `tar -xzf <archive> -C ~/.local/state/superharness`.
- The three recurring sizes suggest the schema is created in one transaction; a fix that keeps
  creating the file but prunes empty ones should therefore key on size *and* row counts, not on
  file size alone.

## Progress 2026-09-18 — `shux state gc` landed, inventory only (report item 2, in part)

Implemented as `src/superharness/commands/state_gc.py`, reachable both as
`shux state-gc` and as the `state` domain's `gc` leaf (`commands/help_catalog.py`).
Flags: `--older-than-days DAYS` (default 30, `0` = no age limit), `--dry-run`,
`--state-root`, `--json`. Covered by `tests/unit/test_state_gc_inventory.py`.

**It deletes nothing, and exposes no option that does.** That is deliberate, and
it is the scope `docs/PLAN-state-db-skeleton-leak.md` §6 sets: real deletion needs
a shared exclusion protocol honoured by every writer, or a proven-quiescent stop
window — *"un verrou SQLite seul ne protège pas le fichier supprimé d'un processus
qui l'a déjà ouvert ; recontrôler juste avant unlink ne suffit pas."* A candidate
here is a snapshot, not authorisation to remove anything.

Two facts found while building it, both load-bearing:

- **Every skeleton also carries a pre-migration snapshot.** `init_db()` calls
  `_backup_db_from_connection` before migrating, so the artifact on disk is
  `state.db` *plus* `state.db.bak.v0`. That is the 348,160-byte group above —
  17,895 of 19,104 databases. Treating the backup as a file a human left behind
  would report nothing as a candidate. Every database file in the directory is
  inspected, the backup included, so a content-free `state.db` whose backup still
  holds rows is not a candidate.
- **Row content is the only usable test, and uncertainty resolves away from
  candidacy.** Confirmed by the table above. A database that is populated, carries
  an unknown table, has a `-wal`/`-shm`/`-journal` sidecar present, is a symlink,
  is unreadable or is locked is classified `ignored`, never a candidate. Nothing
  becomes a candidate on age alone.

Guardrails: only directories named for `project_hash()` (`[0-9a-f]{12}`) are
considered, so pointing `--state-root` at something that is not a state root (say
`$HOME`) reports nothing actionable; each database is opened `mode=ro` and
deliberately **not** `immutable`, because an immutable open asserts a file cannot
change while another process may be writing it; `get_connection()` and `init_db()`
are never called, so the inspection cannot create the skeleton it is looking for;
and rows are read through `iterdump()`, so no table name is ever interpolated into
a query.

**The leak itself is unfixed.** `get_connection()` still calls
`os.makedirs(os.path.dirname(db_path), exist_ok=True)` and
`sqlite3.connect(db_path)` on every open, and `managed_connection()` still runs
`init_db()`'s full schema before a single row is written, so new directories keep
accumulating at the rate measured above. That is iterations 1–3 of the plan, not
this one: iteration 2 changes absent-state reads in `state_reader`, iteration 3
extends that to the remaining readers, and iteration 1 closes the test escapes
that still exist at collection time. "Proposed fix 1" above — do not create the
database until the first write — remains the target, and it is not a small patch.
## Progress 2026-09-18 — iteration 2 landed: task reads no longer create a database

`get_tasks`, `get_task` and `get_top_level_tasks` no longer create a `state.db`
for a project that has neither a database nor legacy YAML state. This is
iteration 2 of `docs/PLAN-state-db-skeleton-leak.md` ("Lire les tâches sans créer
de base"), and it closes the task-read share of the leak that this report
measures.

What was actually creating the skeleton: each reader reached `get_connection()` +
`init_db()`, and those create the per-path directory plus the full schema before
any row is written. A shared guard, `_no_state_to_read()` in
`engine/state_reader.py`, now returns the reader's empty value first. It is built
on the existing non-creating `_has_sqlite_db()` resolver plus a new
`_has_legacy_state()` check on `.superharness/`, so it fires only when there is
genuinely nothing to read.

Three properties were deliberately preserved, and each has a test:

- **A project that has state reads exactly as before** — the guard does not
  over-block.
- **The explicit YAML → SQLite migration still runs** when `.superharness/` is
  present, which is the documented legacy path for fixtures and upgrades.
- **A state-root conflict still raises** rather than degrading into a false "this
  project has no tasks". It surfaces as `engine.state_errors.ConnectionError`,
  the same type `get_connection()` raises for that condition, with the
  `StateDatabaseConflictError` kept as the cause.

Verified: `tests/unit/test_state_reader_no_create.py` (new) and
`tests/unit/test_state_reader_xdg.py` — 14 passed; `tests/unit/` +
`tests/contract/` 4450 passed / 15 skipped / 2 xfailed; and an out-of-pytest
end-to-end run on the production branch confirming the state root is never
created for an absent project.

**Still unfixed after this iteration:** the other readers in this same file —
`get_inbox_items`, `get_handoffs`, `get_failures`, `get_decisions` and
`get_ledger_entries` — still open a connection unconditionally, so an absent
project read through any of them still creates a skeleton. That is iteration 3 of
the plan ("Étendre aux autres lectures d'état"), and the aggregate
contract reader `get_contract_doc` is included there. Iteration 1 (closing the
remaining test-collection escapes) is also still open.
## Progress 2026-09-18 — iteration 3 landed: the read surface no longer creates state

The public read surface of `engine/state_reader.py` no longer creates a database
for an absent project. This is iteration 3 of
`docs/PLAN-state-db-skeleton-leak.md` ("Étendre aux autres lectures d'état").

Covered in this iteration: `get_inbox_items`, `get_handoffs`, `get_failures`,
`get_decisions`, `get_ledger_entries`, and `_read_project_meta` behind the
aggregate `get_contract_doc`. Together with iteration 2's `get_tasks`,
`get_task` and `get_top_level_tasks`, every public reader in the module that
opens a connection now carries its own guard — checked by walking the module's
public functions with `ast` and asserting each connection-opening one is guarded.
`get_contract_doc` is the one aggregate: it opens nothing itself and composes
`get_tasks`, `get_decisions` and `get_failures`.

Two shared checks, deliberately distinct, because the readers differ:

- `_database_absent(project_dir)` — for readers with no YAML ingest path.
  Nothing to read means nothing to create.
- `_no_state_to_read(project_dir)` — database absent *and* no `.superharness/`,
  for the ingest-capable readers. A project that still carries YAML has work to
  do, so the explicit migration path is preserved.

Both translate a state-root conflict to `engine.state_errors.ConnectionError`,
exactly as `get_connection()` does. That also fixes a defect in
`get_ledger_entries`, whose previous raw `_has_sqlite_db()` check let
`StateDatabaseConflictError` escape untranslated — a type no caller of a reader
handles.

`get_contract_doc` composes guarded readers rather than short-circuiting with a
duplicated default document, so its defaults are preserved by construction: an
absent project still returns `{"id": "contract", "goal": "", "tasks": [],
"decisions": [], "failures": []}`, and a future unguarded leaf would be caught by
the aggregate test rather than silently reintroducing the leak.

Verified: `tests/unit/test_state_reader_no_create.py` (now 25 cases) and
`tests/unit/test_state_reader_xdg.py` — 29 passed; `tests/unit/` +
`tests/contract/` 4465 passed / 15 skipped / 2 xfailed; and an out-of-pytest
end-to-end run on the production branch confirming all six readers plus the
aggregate create zero directories and zero databases for an absent project, keep
their defaults, and read back correctly after an explicit write.

**Still unfixed:** iteration 1 of the plan — the test-collection escapes. The
suite's `isolated_state_dir` fixture pins `XDG_STATE_HOME` per test, but the plan
records escapes that happen before collection;
`tests/unit/test_state_collection_isolation.py` does not exist yet. Nothing here
claims "zero skeletons everywhere": the read surface is closed, the
collection-time surface is not.
## Progress 2026-09-18 — iteration 1 probed: no collection-time escape reproduced

Iteration 1 of `docs/PLAN-state-db-skeleton-leak.md` ("Fermer les échappements des
tests") targets state created during pytest **collection**, before the per-test
`isolated_state_dir` fixture becomes active. That escape is **not reproduced on
this revision**, so per the iteration's own instruction no correction was
invented and `tests/conftest.py` is unchanged.

What was measured, twice in a row: collecting the whole suite with a synthetic
`HOME` and neither `XDG_STATE_HOME` nor `SUPERHARNESS_STATE_DIR` set creates
**zero** `state.db` files anywhere under that HOME. This matches the plan's
prerequisite caveat — the 22,485 directories in this report were never reproduced
against this revision, and the archived databases are not evidence about it.

`tests/unit/test_state_collection_isolation.py` keeps the proof as a regression
guard rather than a fix:

- `test_collection_state_stays_in_session_root` — collects twice with a synthetic
  HOME and asserts no state database appears, satisfying the iteration's
  acceptance criterion "deux exécutions successives ne laissent aucune base dans
  le HOME synthétique".
- `test_child_state_is_cleaned_after_session` — runs a child pytest that really
  opens a database, and asserts it honours the inherited `XDG_STATE_HOME` (so
  inheritance is exercised, not assumed), leaves HOME clean, and leaves nothing
  behind once the ephemeral root is removed.

Recorded but deliberately **not** fixed, because it is out of this iteration's
scope and is not state: collection does write
`<HOME>/Library/Logs/superharness/superharness.log` (0 bytes), since
`src/superharness/logging_utils.py:27` resolves the log directory from
`Path.home()`. Read literally, the iteration's criterion "collection and
subprocesses write only into temp space" therefore does not hold — for logs.
Anyone tightening that criterion should treat it as a separate change with its own
justification, not as part of this defect.

Verified: `uv run pytest tests/unit/test_state_collection_isolation.py
tests/unit/test_state_dir_isolation_2026_07_09.py -q` run twice — 6 passed each
time — with the real `~/.local/state/superharness` unchanged at 96 entries
before and after.

**Status of the plan:** iterations 2 and 3 closed the read surface; iteration 4's
inventory command is shipped; iteration 1 found nothing to close on the
collection path. The remaining unverifiable part of this report is its own
measurement history: the 7.5 Gi of directories existed, but nothing here
reproduces their creation on the current code. Treat the stated growth rate as
historical evidence, not as a current property.
