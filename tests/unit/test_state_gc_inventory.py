"""TDD coverage for ``shux state gc`` — inventory only.

Source: ``docs/PLAN-state-db-skeleton-leak.md``, iteration 4
("Inventaire de nettoyage sans suppression") and BUG-2026-09-18.

Two promises are pinned here. The classification is conservative: a populated,
unknown, active, unreadable or otherwise uncertain database is never reported as
a candidate. And the command changes nothing: the default mode and ``--dry-run``
leave the tree byte-identical, so a candidate can never be mistaken for a
deletion that already happened.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from superharness.commands.state_gc import (
    BUSINESS_TABLES,
    CANDIDATE,
    IGNORED,
    KEPT,
    TECHNICAL_TABLES,
    _open_failure_reason,
    build_inventory,
    main,
    render_report,
)
from superharness.engine.db import init_db

DAY = 86400
OLD = 90 * DAY
FRESH = 0
HASH_A = "a1b2c3d4e5f6"
HASH_B = "0f1e2d3c4b5a"

# One minimal satisfiable row per business table, as static SQL.
#
# The table name is a literal in each statement rather than interpolated: table
# names are the one identifier SQLite will not accept as a bound parameter, and
# spelling each statement out keeps this fixture reviewable as its own inventory
# of the live schema. `test_every_business_table_row_is_detected` executes all of
# them, parametrised over BUSINESS_TABLES, so a business table with no row here
# fails loudly instead of quietly reducing coverage.
_ROW_STATEMENTS = {
    "agent_heartbeats": "INSERT INTO agent_heartbeats (agent, updated_at, created_at) VALUES ('x', 'x', 'x')",
    "agent_pulses": "INSERT INTO agent_pulses (task_id, last_seen) VALUES ('x', 'x')",
    "agent_runtime_status": "INSERT INTO agent_runtime_status (updated_at) VALUES ('x')",
    "context_component": "INSERT INTO context_component (component_type, content, first_seen) VALUES ('x', 'x', 'x')",
    "decisions": "INSERT INTO decisions (decision, created_at) VALUES ('x', 'x')",
    "discussion_rounds": "INSERT INTO discussion_rounds (discussion_id, round_number, agent, created_at) VALUES ('x', 1, 'x', 'x')",
    "discussions": "INSERT INTO discussions (topic, created_at) VALUES ('x', 'x')",
    "dispatch_context": "INSERT INTO dispatch_context (task_id, agent, recorded_at) VALUES ('x', 'x', 'x')",
    "dispatch_context_component": "INSERT INTO dispatch_context_component (dispatch_id, position, sha256) VALUES (1, 1, 'x')",
    "dispatch_cursors": "INSERT INTO dispatch_cursors DEFAULT VALUES",
    "events": "INSERT INTO events (ts, kind, payload_json) VALUES ('x', 'x', 'x')",
    "failures": "INSERT INTO failures (created_at) VALUES ('x')",
    "handoffs": "INSERT INTO handoffs (task_id, phase, status, created_at) VALUES ('x', 'x', 'x', 'x')",
    "inbox": "INSERT INTO inbox (task_id, target_agent, status, created_at) VALUES ('x', 'x', 'x', 'x')",
    "ledger": "INSERT INTO ledger (action, created_at) VALUES ('x', 'x')",
    "model_discovery": "INSERT INTO model_discovery (project_id, agent, model_id, probed_at, created_at) VALUES ('x', 'x', 'x', 'x', 'x')",
    "onboarding_state": "INSERT INTO onboarding_state (steps_json, updated_at) VALUES ('x', 'x')",
    "operator_commands": "INSERT INTO operator_commands (idempotency_key, command, sender_id, created_at) VALUES ('x', 'x', 'x', 'x')",
    "profile_trials": "INSERT INTO profile_trials (profile_key, baseline_success_rate, trial_started_at) VALUES ('x', 1, 'x')",
    "project_meta": "INSERT INTO project_meta DEFAULT VALUES",
    "review_store": "INSERT INTO review_store (owner) VALUES ('x')",
    "summarizer_calls": "INSERT INTO summarizer_calls (provider, called_at, success) VALUES ('x', 'x', 1)",
    "task_artifacts": "INSERT INTO task_artifacts (task_id, path, created_at) VALUES ('x', 'x', 'x')",
    "task_dependencies": "INSERT INTO task_dependencies (dependent_task_id, prerequisite_task_id) VALUES ('x', 'x')",
    "task_observations": "INSERT INTO task_observations (task_id, phase, summary, created_at) VALUES ('x', 'x', 'x', 'x')",
    "task_usage": "INSERT INTO task_usage (task_id, agent, recorded_at) VALUES ('x', 'x', 'x')",
    "tasks": "INSERT INTO tasks (id, title, status, created_at) VALUES ('t1', 'T', 'pending', '2026-01-01T00:00:00Z')",
    "watcher_cooldowns": "INSERT INTO watcher_cooldowns (last_run_epoch) VALUES (1)",
    "watcher_instance": "INSERT INTO watcher_instance (pid, started_at, last_heartbeat) VALUES (1, 'x', 'x')",
}


def _age(path: Path, seconds: float) -> None:
    when = time.time() - seconds
    for entry in [path, *path.rglob("*")]:
        os.utime(entry, (when, when))


def _make_dir(root: Path, name: str = HASH_A, age_s: float = OLD) -> Path:
    """A schema-created, content-free state directory — the leaked artifact."""
    directory = root / name
    directory.mkdir(parents=True)
    conn = sqlite3.connect(directory / "state.db")
    try:
        init_db(conn)
        conn.commit()
    finally:
        conn.close()
    _age(directory, age_s)
    return directory


def _make_populated(root: Path, table: str, name: str = HASH_A) -> Path:
    directory = _make_dir(root, name=name)
    conn = sqlite3.connect(directory / "state.db")
    try:
        conn.execute(_ROW_STATEMENTS[table])
        conn.commit()
    finally:
        conn.close()
    return directory


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Every file under *root* with its size and content hash."""
    state: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            state[str(path.relative_to(root))] = (
                path.stat().st_size,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
    return state


def _verdict(root: Path, name: str = HASH_A, older_than_days: int = 30):
    summary = build_inventory(root, older_than_days=older_than_days, now=time.time())
    return next(e for e in summary["entries"] if e["path"] == name)


# --- the command changes nothing ---------------------------------------------


def test_gc_dry_run_preserves_all_files(tmp_path):
    """Acceptance: the default mode and --dry-run change no file."""
    root = tmp_path / "state"
    _make_dir(root, HASH_A)
    _make_populated(root, "ledger", name=HASH_B)
    (root / "not-a-hash").mkdir()
    (root / "not-a-hash" / "state.db").write_bytes(b"")

    before = _snapshot(root)
    build_inventory(root, older_than_days=30, now=time.time())
    build_inventory(root, older_than_days=0, now=time.time())
    main(["--state-root", str(root)])
    main(["--state-root", str(root), "--dry-run"])

    assert _snapshot(root) == before


def test_two_inventories_agree_on_counts_and_sizes(tmp_path):
    """Acceptance: two synthetic inventories give the same counts and sizes."""
    root = tmp_path / "state"
    _make_dir(root, HASH_A)
    _make_populated(root, "ledger", name=HASH_B)
    _make_dir(root, "111111111111", age_s=FRESH)
    (root / "222222222222").mkdir()
    (root / "222222222222" / "state.db").write_bytes(b"not a database")
    _age(root / "222222222222", OLD)

    first = build_inventory(root, older_than_days=30, now=time.time())
    second = build_inventory(root, older_than_days=30, now=time.time())

    assert first["counts"] == second["counts"]
    assert first["bytes"] == second["bytes"]
    assert first["entries"] == second["entries"]


# --- conservative classification ---------------------------------------------


def test_gc_keeps_every_populated_business_table(tmp_path):
    """A row anywhere in the live schema must beat the age cutoff."""
    root = tmp_path / "state"
    _make_populated(root, "ledger")

    assert _verdict(root)["bucket"] == KEPT
    assert _verdict(root)["reason"] == "holds rows (state.db)"


@pytest.mark.parametrize("table", sorted(BUSINESS_TABLES))
def test_every_business_table_row_is_detected(tmp_path, table):
    """Parametrised over the real schema, not only the seven tables in the report."""
    root = tmp_path / "state"
    _make_populated(root, table)

    verdict = _verdict(root)

    assert verdict["bucket"] == KEPT, f"{table} was not recognised as populated"
    assert verdict["reason"] == "holds rows (state.db)"


def test_business_table_set_matches_live_schema(tmp_path):
    """The known-table set must not rot behind a schema change.

    A table added to `init_db()` and not declared here would be classified
    "unknown table" and the directory silently dropped from candidacy — safe, but
    the staleness would go unnoticed. This fails instead.
    """
    probe = tmp_path / "probe.db"
    conn = sqlite3.connect(probe)
    try:
        init_db(conn)
        conn.commit()
        live = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("sqlite_")
        }
    finally:
        conn.close()

    assert live - TECHNICAL_TABLES == set(BUSINESS_TABLES)


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        ("unknown_table", "state.db: unknown table 'mystery'"),
        ("corrupt", "state.db: unreadable"),
        ("sidecar", "sidecar present (state.db-wal)"),
        ("extra_file", "extra files"),
        ("no_database", "no state.db"),
    ],
)
def test_gc_skips_unsafe_or_unknown_databases(tmp_path, setup, reason):
    root = tmp_path / "state"
    directory = _make_dir(root)

    if setup == "unknown_table":
        conn = sqlite3.connect(directory / "state.db")
        conn.execute("CREATE TABLE mystery (x INTEGER)")
        conn.execute("INSERT INTO mystery VALUES (1)")
        conn.commit()
        conn.close()
    elif setup == "corrupt":
        (directory / "state.db").write_bytes(b"this is not a sqlite database")
    elif setup == "sidecar":
        (directory / "state.db-wal").write_bytes(b"")
    elif setup == "extra_file":
        (directory / "notes.txt").write_text("a human put this here")
    elif setup == "no_database":
        # The backup stays on purpose: this case is a directory that has files but
        # no database, not an empty one (which has its own classification).
        (directory / "state.db").unlink()
    _age(directory, OLD)

    verdict = _verdict(root)

    assert verdict["bucket"] == IGNORED
    assert verdict["reason"] == reason


def test_gc_ignores_a_symlinked_state_directory(tmp_path):
    root = tmp_path / "state"
    target = tmp_path / "elsewhere"
    target.mkdir()
    root.mkdir()
    (root / HASH_A).symlink_to(target, target_is_directory=True)

    verdict = _verdict(root)

    assert verdict["bucket"] == IGNORED
    assert verdict["reason"] == "symlink"


def test_gc_ignores_a_directory_whose_name_is_not_a_project_hash(tmp_path):
    root = tmp_path / "state"
    odd = root / "not-a-hash"
    odd.mkdir(parents=True)
    (odd / "state.db").write_bytes(b"")

    verdict = _verdict(root, name="not-a-hash")

    assert verdict["bucket"] == IGNORED
    assert verdict["reason"] == "not a state directory"


def test_open_failure_reason_distinguishes_a_lock():
    assert _open_failure_reason(sqlite3.OperationalError("database is locked")) == "locked"
    assert (
        _open_failure_reason(sqlite3.DatabaseError("file is not a database"))
        == "unreadable"
    )


# --- what actually becomes a candidate ---------------------------------------


def test_gc_reports_content_free_old_directory_as_candidate(tmp_path):
    root = tmp_path / "state"
    _make_dir(root, age_s=OLD)

    verdict = _verdict(root)

    assert verdict["bucket"] == CANDIDATE
    assert verdict["reason"] == "content-free"


def test_gc_reclaims_the_shape_the_backend_actually_writes(tmp_path):
    """The artifact is `state.db` plus its pre-migration snapshot.

    17,895 of 19,104 databases on the reporting machine were 348,160 bytes —
    the database and `state.db.bak.v0` together. Asserting the shape keeps this
    honest if `init_db()` ever stops writing the snapshot.
    """
    root = tmp_path / "state"
    directory = _make_dir(root, age_s=OLD)

    assert sorted(p.name for p in directory.iterdir()) == [
        "state.db",
        "state.db.bak.v0",
    ]
    assert _verdict(root)["bucket"] == CANDIDATE


def test_gc_keeps_a_directory_whose_migration_backup_holds_rows(tmp_path):
    """A content-free `state.db` does not make the backup disposable."""
    root = tmp_path / "state"
    directory = _make_dir(root, age_s=OLD)
    conn = sqlite3.connect(directory / "state.db.bak.v0")
    try:
        conn.execute("CREATE TABLE legacy (x INTEGER)")
        conn.execute("INSERT INTO legacy VALUES (1)")
        conn.commit()
    finally:
        conn.close()
    _age(directory, OLD)

    # `legacy` is not a known table, so the backup is what makes this ignored.
    verdict = _verdict(root)

    assert verdict["bucket"] == IGNORED
    assert verdict["reason"] == "state.db.bak.v0: unknown table 'legacy'"


def test_gc_keeps_recently_used_directory(tmp_path):
    root = tmp_path / "state"
    _make_dir(root, age_s=FRESH)

    verdict = _verdict(root, older_than_days=30)

    assert verdict["bucket"] == KEPT
    assert verdict["reason"] == "recently used"


def test_older_than_days_zero_ignores_age(tmp_path):
    root = tmp_path / "state"
    _make_dir(root, age_s=FRESH)

    assert _verdict(root, older_than_days=0)["bucket"] == CANDIDATE


def test_older_than_days_zero_ignores_a_future_mtime(tmp_path):
    """`--older-than-days 0` means "ignore age", not "compare against now".

    A directory touched an hour in the future is still a candidate, because with
    the age gate disabled there is nothing for its mtime to be compared to.

    This pins the documented contract without depending on filesystem mtime
    resolution. The previous implementation computed `cutoff = now - 0 * 86400`
    and compared against it anyway, so it passed on macOS only because a freshly
    touched file's mtime happened to be strictly earlier than the call-site
    `now`; on Windows the coarser granularity put mtime at or past that cutoff
    and returned `kept`. A future mtime makes the same defect fail everywhere.
    """
    root = tmp_path / "state"
    directory = _make_dir(root, age_s=FRESH)
    future = time.time() + 3600
    for entry in [directory, *directory.rglob("*")]:
        os.utime(entry, (future, future))

    assert _verdict(root, older_than_days=0)["bucket"] == CANDIDATE


def test_negative_age_is_refused(tmp_path):
    with pytest.raises(ValueError):
        build_inventory(tmp_path, older_than_days=-1)


def test_cli_refuses_a_negative_age(tmp_path, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--state-root", str(tmp_path), "--older-than-days", "-1"])

    assert excinfo.value.code == 2
    assert "must be >= 0" in capsys.readouterr().err


def test_a_row_outside_the_documented_tables_is_still_kept(tmp_path):
    """Regression: the report named seven tables; the schema has 29."""
    root = tmp_path / "state"
    _make_populated(root, "dispatch_cursors")

    assert _verdict(root)["bucket"] == KEPT


# --- reporting contract -------------------------------------------------------


def test_report_exposes_candidates_kept_and_ignored_with_reasons(tmp_path):
    root = tmp_path / "state"
    _make_dir(root, HASH_A)
    _make_populated(root, "ledger", name=HASH_B)

    summary = build_inventory(root, older_than_days=30, now=time.time())
    text = render_report(summary)

    assert summary["counts"][CANDIDATE] == 1
    assert summary["counts"][KEPT] == 1
    assert summary["bytes"][CANDIDATE] > 0
    assert summary["bytes"]["total"] > summary["bytes"][CANDIDATE]
    assert "candidate: 1" in text
    assert "kept: 1" in text
    assert "never deletes" in text.lower() or "removes nothing" in text.lower()


def test_inventory_of_a_missing_root_is_empty(tmp_path):
    summary = build_inventory(tmp_path / "does-not-exist", older_than_days=30)

    assert summary["entries"] == []
    assert summary["counts"] == {CANDIDATE: 0, KEPT: 0, IGNORED: 0}


def test_cli_json_output_is_parseable(tmp_path, capsys):
    import json

    root = tmp_path / "state"
    _make_dir(root)

    main(["--state-root", str(root), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"][CANDIDATE] == 1


def test_cli_exposes_no_deletion_option(capsys):
    """The plan is explicit: no deletion option may be presented as implemented."""
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    assert "never deletes" in out
    for forbidden in ("--delete", "--remove", "--apply", "--force"):
        assert forbidden not in out


def test_smoke_state_group_help():
    """Smoke: the command is reachable through the `state` domain group."""
    result = subprocess.run(
        [sys.executable, "-m", "superharness", "state", "gc", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "never deletes" in result.stdout
