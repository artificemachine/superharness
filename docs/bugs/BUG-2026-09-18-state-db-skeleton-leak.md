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
