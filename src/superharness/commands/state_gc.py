"""State-directory inventory — BUG-2026-09-18-state-db-skeleton-leak.

**Inventory only. This command never deletes anything, and it exposes no option
that does.** A candidate is a snapshot of what looks content-free at the moment
it was taken; it is not authorisation to remove anything. Real deletion needs a
shared exclusion protocol honoured by every writer, or a proven-quiescent stop
window — an SQLite lock does not protect an already-open file from being
unlinked underneath its holder, and re-checking content immediately before an
unlink is not sufficient. See `docs/PLAN-state-db-skeleton-leak.md` §6.

Why the leak exists: `resolve_xdg_state_db_path()` gives every distinct absolute
project path its own `<state-dir>/<12-char-hash>/state.db`, and opening that path
creates the directory and the full schema before a single row is written. On the
reporting machine 22,485 such directories (~7.5 Gi) had accumulated. Of 3,372
aged databases, 112 did hold rows — so age alone is never evidence, and the hash
in the directory name is a one-way digest of a path nobody recorded.

Structure: classification is pure (`classify_directory`, `build_inventory`) and
CLI rendering is separate (`render_report`, `main`).
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from superharness.utils.paths import resolve_state_dir

STATE_DB = "state.db"
DEFAULT_OLDER_THAN_DAYS = 30

# A state directory is named for `project_hash()` — sha256 hexdigest[:12].
_STATE_DIRECTORY = re.compile(r"[0-9a-f]{12}")

# `init_db()` snapshots the pre-migration database before upgrading it, so the
# artifact on disk is the database *plus* `state.db.bak.v<N>`. The dominant
# leaked size (348,160 bytes, 17,895 of 19,104 databases) is database plus that
# backup, so a backup is expected company, not a file someone left behind.
_MIGRATION_BACKUP = re.compile(r"state\.db\.bak\.v\d+$")

# A present sidecar means a writer may hold this database. Reading it is fine,
# but `-shm` is an mmap and `-wal` is live state; a read-only open that has to
# touch them is a mutation of something we do not own. Such a directory is
# classified `ignored` and left completely alone.
_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")

# Tables the state backend keeps for its own bookkeeping. Excluding them is what
# makes an empty-but-migrated database recognisable as content-free: without
# this, `init_db()` writes a migration row into every skeleton it creates and
# nothing would ever look empty.
TECHNICAL_TABLES = frozenset({"schema_migrations", "sqlite_sequence"})

# The business tables of the live schema (schema version 39), read from a
# database built by `init_db()`. A database holding a table outside
# BUSINESS_TABLES | TECHNICAL_TABLES has a schema this classifier does not know,
# so it is classified `ignored` — never a candidate. Widening the schema means
# widening this set; `test_business_table_set_matches_live_schema` fails if it
# drifts, so the list cannot rot silently.
BUSINESS_TABLES = frozenset(
    {
        "agent_heartbeats",
        "agent_pulses",
        "agent_runtime_status",
        "context_component",
        "decisions",
        "discussion_rounds",
        "discussions",
        "dispatch_context",
        "dispatch_context_component",
        "dispatch_cursors",
        "events",
        "failures",
        "handoffs",
        "inbox",
        "ledger",
        "model_discovery",
        "onboarding_state",
        "operator_commands",
        "profile_trials",
        "project_meta",
        "review_store",
        "summarizer_calls",
        "task_artifacts",
        "task_dependencies",
        "task_observations",
        "task_usage",
        "tasks",
        "watcher_cooldowns",
        "watcher_instance",
    }
)

CANDIDATE = "candidate"
KEPT = "kept"
IGNORED = "ignored"


@dataclass(frozen=True)
class Verdict:
    """One state directory's classification. `bytes` is its size on disk."""

    path: str
    bucket: str
    reason: str
    bytes: int


def _is_state_directory_name(name: str) -> bool:
    return _STATE_DIRECTORY.fullmatch(name) is not None


def _is_database_file(name: str) -> bool:
    return name == STATE_DB or _MIGRATION_BACKUP.fullmatch(name) is not None


def _is_allowed_file(name: str) -> bool:
    if _is_database_file(name):
        return True
    return any(name == STATE_DB + suffix for suffix in _SIDECAR_SUFFIXES)


def _directory_size(directory: Path) -> int:
    total = 0
    for entry in directory.rglob("*"):
        try:
            if entry.is_file() and not entry.is_symlink():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def _newest_mtime(directory: Path) -> float:
    newest = directory.stat().st_mtime
    for entry in directory.iterdir():
        try:
            newest = max(newest, entry.stat().st_mtime)
        except OSError:
            continue
    return newest


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _has_business_rows(conn: sqlite3.Connection) -> bool:
    """True if any business table holds a row.

    `iterdump()` reaches the data through plain SELECTs, so a table name never
    becomes part of a query string — table names are the one identifier SQLite
    will not accept as a bound parameter. Iteration stops at the first row found.
    """
    for line in conn.iterdump():
        if not line.startswith("INSERT INTO "):
            continue
        remainder = line[len('INSERT INTO "') :]
        end = remainder.find('"')
        if end <= 0:
            # A dump line whose table cannot be read is not something to guess
            # about: treat the database as holding content.
            return True
        if remainder[:end] in BUSINESS_TABLES:
            return True
    return False


def _inspect_database(path: Path) -> tuple[str, str]:
    """Classify one database file as KEPT or IGNORED, with a reason.

    Opened `mode=ro` and deliberately **not** `immutable`: an immutable open
    asserts the file cannot change, which is a lie about a database another
    process may be writing. A file the classifier cannot read is never a
    candidate — unknown content is the one thing that must not be reclaimed.
    """
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return IGNORED, _open_failure_reason(exc)

    try:
        names = _table_names(conn)
        unknown = sorted(
            name
            for name in names
            if not name.startswith("sqlite_")
            and name not in BUSINESS_TABLES
            and name not in TECHNICAL_TABLES
        )
        if unknown:
            return IGNORED, f"unknown table {unknown[0]!r}"

        if _has_business_rows(conn):
            return KEPT, "holds rows"
        return KEPT, "no rows"
    except sqlite3.Error as exc:
        return IGNORED, _open_failure_reason(exc)
    except (ValueError, TypeError) as exc:
        return IGNORED, f"unreadable ({type(exc).__name__})"
    finally:
        conn.close()


def _open_failure_reason(exc: sqlite3.Error) -> str:
    message = str(exc).lower()
    if "locked" in message or "busy" in message:
        return "locked"
    return "unreadable"


def classify_directory(directory: Path, cutoff: float | None) -> Verdict:
    """Classify one candidate directory. Pure: touches nothing, writes nothing.

    Every uncertainty resolves to `ignored` rather than `candidate`, because a
    wrongly ignored directory costs only the chance to reclaim it, while a
    wrongly reported candidate invites a deletion that does not need to happen.

    `cutoff` is `None` when age is to be ignored. The mtime is then never
    consulted, so `recently used` cannot be returned and a content-free
    directory is a candidate whatever its timestamp.
    """
    size = _directory_size(directory)

    if directory.is_symlink():
        return Verdict(directory.name, IGNORED, "symlink", size)

    try:
        entries = {entry.name for entry in directory.iterdir()}
    except OSError:
        return Verdict(directory.name, IGNORED, "unreadable", size)

    if not entries:
        return Verdict(directory.name, CANDIDATE, "empty directory", size)

    sidecars = sorted(
        name
        for name in entries
        if name in {STATE_DB + suffix for suffix in _SIDECAR_SUFFIXES}
    )
    if sidecars:
        return Verdict(directory.name, IGNORED, f"sidecar present ({sidecars[0]})", size)

    if any(not _is_allowed_file(name) for name in entries):
        return Verdict(directory.name, IGNORED, "extra files", size)

    if STATE_DB not in entries:
        return Verdict(directory.name, IGNORED, "no state.db", size)

    for name in sorted(entries):
        if not _is_database_file(name):
            continue
        database = directory / name
        if database.is_symlink():
            return Verdict(directory.name, IGNORED, f"symlink ({name})", size)
        bucket, reason = _inspect_database(database)
        if bucket is IGNORED:
            return Verdict(directory.name, IGNORED, f"{name}: {reason}", size)
        if reason == "holds rows":
            return Verdict(directory.name, KEPT, f"holds rows ({name})", size)

    if cutoff is not None and _newest_mtime(directory) >= cutoff:
        return Verdict(directory.name, KEPT, "recently used", size)

    return Verdict(directory.name, CANDIDATE, "content-free", size)


def build_inventory(
    state_root: str | Path,
    older_than_days: int = DEFAULT_OLDER_THAN_DAYS,
    now: float | None = None,
) -> dict:
    """Classify every state directory under *state_root*. Never mutates.

    `older_than_days=0` means "ignore age": every content-free directory is
    reported as a candidate regardless of when it was last touched. The age
    threshold is measured on the files that are actually present.
    """
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")

    root = Path(state_root)
    now = time.time() if now is None else now
    cutoff = None if older_than_days == 0 else now - older_than_days * 86400

    verdicts: list[Verdict] = []
    if root.is_dir():
        for entry in sorted(root.iterdir()):
            if entry.name in {STATE_DB} or entry.is_file():
                verdicts.append(
                    Verdict(entry.name, IGNORED, "not a state directory", 0)
                )
                continue
            if not _is_state_directory_name(entry.name):
                verdicts.append(
                    Verdict(entry.name, IGNORED, "not a state directory", 0)
                )
                continue
            verdicts.append(classify_directory(entry, cutoff))

    counts = {CANDIDATE: 0, KEPT: 0, IGNORED: 0}
    sizes = {CANDIDATE: 0, KEPT: 0, IGNORED: 0}
    for verdict in verdicts:
        counts[verdict.bucket] += 1
        sizes[verdict.bucket] += verdict.bytes

    return {
        "state_root": str(root),
        "older_than_days": older_than_days,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "counts": counts,
        "bytes": {**sizes, "total": sum(sizes.values())},
        "entries": [
            {
                "path": verdict.path,
                "bucket": verdict.bucket,
                "reason": verdict.reason,
                "bytes": verdict.bytes,
            }
            for verdict in verdicts
        ],
    }


def render_report(summary: dict) -> str:
    """Human-readable rendering. Reports; never acts."""
    counts = summary["counts"]
    sizes = summary["bytes"]
    lines = [
        f"State inventory: {summary['state_root']}",
        f"age threshold: {summary['older_than_days']} day(s) "
        f"(files present; older than {summary['older_than_days']} days)",
        "",
        "A candidate is a snapshot of what looks content-free now. It is not "
        "permission to delete anything; this command removes nothing.",
        "",
    ]

    for bucket in (CANDIDATE, KEPT, IGNORED):
        matching = [e for e in summary["entries"] if e["bucket"] == bucket]
        if not matching:
            continue
        lines.append(f"{bucket}: {counts[bucket]} ({sizes[bucket]} bytes)")
        for entry in matching:
            lines.append(f"   {entry['reason']:<28} {entry['path']}")
        lines.append("")

    lines.append(
        f"Totals: {counts[CANDIDATE]} candidate(s), {counts[KEPT]} kept, "
        f"{counts[IGNORED]} ignored, {sizes['total']} bytes inspected"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    parser = argparse.ArgumentParser(
        prog="state-gc",
        description=(
            "Report state directories that look content-free. Inventory only: "
            "this command never deletes anything."
        ),
    )
    parser.add_argument(
        "--state-root",
        default=None,
        help="State root to inspect (default: resolve_state_dir())",
    )
    parser.add_argument(
        "--older-than-days",
        type=int,
        default=DEFAULT_OLDER_THAN_DAYS,
        metavar="DAYS",
        help="Report content-free directories untouched for DAYS (0 = no age limit)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Explicit no-op: the default already changes no file",
    )
    parser.add_argument("--json", action="store_true", default=False)
    opts = parser.parse_args(argv)

    if opts.older_than_days < 0:
        parser.error("--older-than-days must be >= 0")

    root = opts.state_root or resolve_state_dir()
    summary = build_inventory(root, older_than_days=opts.older_than_days)

    if opts.json:
        print(json.dumps(summary, indent=2))
    else:
        print(render_report(summary))


if __name__ == "__main__":
    main()
