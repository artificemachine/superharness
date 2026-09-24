# State Authority Stage 1 — Transition Plan

Status: **mergeable code preparation; shared rollout prohibited**

This plan accompanies the Stage 1 state-authority fix. Stage 1 makes
`SUPERHARNESS_STATE_DIR` an explicit authority, removes resolver drift, and
detects competing state databases. It does **not** authorize a shared SQLite
database on NFS and does not solve live-session delivery.

The Stage 1 pull request may be reviewed and merged without activating the new
shared path. Merge and rollout are separate owner decisions.

## Interim operating regime

Until Stage 2 is designed and approved:

- **Same host, <primary-workstation>:** plain `shux` continues to use the local XDG database.
  PM and prod-insider may use local `shux discuss` only
  while both participants keep an active read/respond loop on the discussion
  ID. A written round does not wake an idle session.
- **Between hosts:** use the project append-only NAS mailbox. Use a human relay
  when the message is urgent.
- **`shuxx-talk` is FAILED/NON-RELIABLE** and must not be used for
  communication or as proof of delivery.
- **Do not create**
  `<NAS-MOUNT>/<owner-workspace>/.claude/shux-shared/<hash>/state.db`.
  In particular, do not test the candidate build through a wrapper that exports
  that state directory.
- No host may set `SUPERHARNESS_STATE_DIR` to
  `<NAS-MOUNT>/<owner-workspace>/.claude/shux-shared` before
  the separate Stage 2 owner decision.
- Existing XDG and legacy databases remain independent historical authorities.
  Do not merge, copy, or select between them implicitly.

## Pre-cutover inventory and freeze

No cutover starts until an owner-approved window is declared.

1. On <primary-workstation>, <shared-router-host>, and the owner's remote host, record:
   - installed Superharness version and wrapper version;
   - project realpath and computed project hash;
   - resolved database path with and without `SUPERHARNESS_STATE_DIR`;
   - database size, modification time, and SHA-256.
2. Inventory every discussion in each database with its ID, status, last round,
   participants, and last activity time.
3. Freeze new discussions and submissions at the declared cutoff. Stop
   watchers and wrappers before backups.
4. Prefer resolving or cancelling active discussions before the cutoff.
   Anything still active becomes a named read-only archive; histories from
   different databases are never silently combined.

## Backup and disposition

- Back up each SQLite database independently while writers are stopped, using
  SQLite's backup operation rather than a live file copy.
- Preserve the source host, source path, project hash, timestamp, checksum, and
  discussion inventory beside each backup.
- Keep legacy NAS and per-host XDG backups read-only for audit.
- If a one-shot migration is later approved, migrate only the explicitly
  selected authority into an empty destination and verify row counts,
  discussion IDs, latest rounds, integrity, and checksums before enabling any
  writer.

## Future synchronized rollout

Activation is a separate owner decision. The primary workstation, the shared
router host, and the remote host must receive the same reviewed Superharness
build and matching wrapper behavior in one window. The wrapper is delivered
separately because it is outside this repository.

Before unfreezing, verify on every host that:

1. the explicit state directory resolves to the same intended authority;
2. no fallback database receives a probe write;
3. `shuxx-talk` reads the same path it writes, if it is re-enabled;
4. no process can create the prohibited shared NFS SQLite database by fallback;
5. an end-to-end canary is visible from every intended participant.

Failure of any check keeps the runtime frozen.

## Rollback

1. Stop all writers and watchers.
2. Restore the previous package and wrapper versions on every upgraded host.
3. Remove the explicit state-directory activation from the runtime environment.
4. Re-select the pre-cutover database recorded for each host; do not copy a
   shared database back over a legacy or XDG database.
5. Run SQLite integrity checks and compare the inventories to the pre-cutover
   record before resuming the interim regime.

Any rounds written after the cutoff are quarantined for manual reconciliation;
rollback must not overwrite them.

## Stage 2 boundary

Stage 2 requires its own design review and implementation. Its exit criterion
is:

> A pending discussion round either wakes a registered live consumer or emits
> an explicit, bounded-latency delivery alert.

Lease, heartbeat, acknowledgement, watcher policy, session injection, and a
single-writer service or PostgreSQL backend belong to Stage 2. None is implied
or activated by the Stage 1 pull request.
