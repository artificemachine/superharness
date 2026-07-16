"""Tests for the migrate-state command."""
from __future__ import annotations

import os
import sqlite3
import pytest
from unittest.mock import patch

from superharness.commands.migrate_state import run_migrate_state


@pytest.fixture()
def project_dir(tmp_path):
    harness = tmp_path / ".superharness"
    harness.mkdir()
    return str(tmp_path)


@pytest.fixture()
def legacy_db(project_dir):
    db_path = os.path.join(project_dir, ".superharness", "state.sqlite3")
    with open(db_path, "wb") as f:
        f.write(b"SQLite format 3\x00" + b"\x00" * 84)
    return db_path


def _xdg_db_path(project_dir: str) -> str:
    from superharness.utils.paths import resolve_xdg_state_db_path
    return resolve_xdg_state_db_path(project_dir)


class TestNothingToMigrate:
    def test_no_legacy_no_xdg_returns_0(self, project_dir):
        assert run_migrate_state(project_dir) == 0

    def test_no_legacy_but_xdg_exists_returns_0(self, project_dir):
        xdg = _xdg_db_path(project_dir)
        os.makedirs(os.path.dirname(xdg), exist_ok=True)
        open(xdg, "w").close()
        assert run_migrate_state(project_dir) == 0


class TestAbortConditions:
    def test_xdg_already_exists_warns_and_removes_legacy(self, project_dir, legacy_db):
        # Iter 12: split-brain is now resolved gracefully (remove legacy, return 0)
        # instead of aborting. The XDG db is the active source of truth.
        xdg = _xdg_db_path(project_dir)
        os.makedirs(os.path.dirname(xdg), exist_ok=True)
        with open(xdg, "wb") as f:
            f.write(b"existing")
        assert run_migrate_state(project_dir) == 0
        assert not os.path.isfile(legacy_db), "legacy db must be removed in split-brain resolution"

    def test_xdg_not_overwritten_on_abort(self, project_dir, legacy_db):
        xdg = _xdg_db_path(project_dir)
        os.makedirs(os.path.dirname(xdg), exist_ok=True)
        original = b"existing content"
        with open(xdg, "wb") as f:
            f.write(original)
        run_migrate_state(project_dir)
        assert open(xdg, "rb").read() == original


class TestSuccessfulMigration:
    def test_copies_db_to_xdg(self, project_dir, legacy_db):
        assert run_migrate_state(project_dir) == 0
        xdg = _xdg_db_path(project_dir)
        assert os.path.isfile(xdg)

    def test_xdg_content_matches_legacy(self, project_dir, legacy_db):
        original = open(legacy_db, "rb").read()
        run_migrate_state(project_dir)
        xdg = _xdg_db_path(project_dir)
        assert open(xdg, "rb").read() == original

    def test_legacy_removed_by_default(self, project_dir, legacy_db):
        run_migrate_state(project_dir)
        assert not os.path.isfile(legacy_db)

    def test_keep_legacy_flag_preserves_source(self, project_dir, legacy_db):
        run_migrate_state(project_dir, keep_legacy=True)
        assert os.path.isfile(legacy_db)

    def test_wal_files_copied_when_present(self, project_dir, legacy_db):
        wal = legacy_db + "-wal"
        shm = legacy_db + "-shm"
        with open(wal, "wb") as f:
            f.write(b"wal data")
        with open(shm, "wb") as f:
            f.write(b"shm data")
        run_migrate_state(project_dir)
        xdg = _xdg_db_path(project_dir)
        assert open(xdg + "-wal", "rb").read() == b"wal data"
        assert open(xdg + "-shm", "rb").read() == b"shm data"

    def test_wal_files_removed_with_legacy(self, project_dir, legacy_db):
        wal = legacy_db + "-wal"
        with open(wal, "wb") as f:
            f.write(b"wal data")
        run_migrate_state(project_dir)
        assert not os.path.isfile(wal)

    def test_wal_files_kept_with_keep_legacy(self, project_dir, legacy_db):
        wal = legacy_db + "-wal"
        with open(wal, "wb") as f:
            f.write(b"wal data")
        run_migrate_state(project_dir, keep_legacy=True)
        assert os.path.isfile(wal)

    def test_xdg_dir_created_if_missing(self, project_dir, legacy_db):
        xdg = _xdg_db_path(project_dir)
        xdg_dir = os.path.dirname(xdg)
        # Directory should not exist yet
        assert not os.path.isdir(xdg_dir)
        run_migrate_state(project_dir)
        assert os.path.isdir(xdg_dir)


class TestDryRun:
    def test_dry_run_returns_0(self, project_dir, legacy_db):
        assert run_migrate_state(project_dir, dry_run=True) == 0

    def test_dry_run_does_not_copy(self, project_dir, legacy_db):
        run_migrate_state(project_dir, dry_run=True)
        xdg = _xdg_db_path(project_dir)
        assert not os.path.isfile(xdg)

    def test_dry_run_does_not_remove_legacy(self, project_dir, legacy_db):
        run_migrate_state(project_dir, dry_run=True)
        assert os.path.isfile(legacy_db)


def _make_sqlite_with_columns(path: str, columns: list[str]) -> None:
    if os.path.exists(path):
        os.remove(path)  # overwrite any placeholder (e.g. the legacy_db fixture's fake header)
    conn = sqlite3.connect(path)
    try:
        cols_sql = ", ".join(f"{c} TEXT" for c in ["id"] + columns)
        conn.execute(f"CREATE TABLE agent_heartbeats ({cols_sql})")
        conn.commit()
    finally:
        conn.close()


class TestSplitBrainSchemaComparison:
    """A DB can claim every migration applied (schema_migrations + user_version)
    while missing columns a migration was supposed to add — see
    db._heal_known_migration_drift. Blindly trusting "XDG is always ahead"
    and deleting the legacy copy would make that corruption permanent."""

    def test_refuses_when_xdg_missing_columns_legacy_has(self, project_dir, legacy_db):
        _make_sqlite_with_columns(legacy_db, ["runtime", "active_task"])
        xdg = _xdg_db_path(project_dir)
        os.makedirs(os.path.dirname(xdg), exist_ok=True)
        _make_sqlite_with_columns(xdg, [])  # xdg is schema-behind

        result = run_migrate_state(project_dir)

        assert result == 1
        assert os.path.isfile(legacy_db), "must not delete the schema-ahead legacy db"
        assert os.path.isfile(xdg), "must not touch the xdg db either"

    def test_proceeds_when_xdg_not_behind(self, project_dir, legacy_db):
        _make_sqlite_with_columns(legacy_db, ["runtime"])
        xdg = _xdg_db_path(project_dir)
        os.makedirs(os.path.dirname(xdg), exist_ok=True)
        _make_sqlite_with_columns(xdg, ["runtime", "active_task"])  # xdg equal-or-ahead

        result = run_migrate_state(project_dir)

        assert result == 0
        assert not os.path.isfile(legacy_db), "legacy should still be removed when xdg isn't behind"

    def test_dry_run_does_not_touch_files_when_xdg_behind(self, project_dir, legacy_db):
        _make_sqlite_with_columns(legacy_db, ["runtime"])
        xdg = _xdg_db_path(project_dir)
        os.makedirs(os.path.dirname(xdg), exist_ok=True)
        _make_sqlite_with_columns(xdg, [])

        result = run_migrate_state(project_dir, dry_run=True)

        assert result == 1
        assert os.path.isfile(legacy_db)
        assert os.path.isfile(xdg)


class TestSizeMismatchRollback:
    def test_size_mismatch_returns_1_and_removes_partial(self, project_dir, legacy_db):
        xdg = _xdg_db_path(project_dir)

        def bad_copy(src, dst):
            import shutil
            shutil.copy2(src, dst)
            # Truncate destination to simulate a partial copy
            with open(dst, "wb") as f:
                f.write(b"truncated")

        with patch("shutil.copy2", side_effect=bad_copy):
            result = run_migrate_state(project_dir)

        assert result == 1
        assert not os.path.isfile(xdg)

    def test_size_mismatch_preserves_legacy(self, project_dir, legacy_db):
        def bad_copy(src, dst):
            import shutil
            shutil.copy2(src, dst)
            with open(dst, "wb") as f:
                f.write(b"truncated")

        with patch("shutil.copy2", side_effect=bad_copy):
            run_migrate_state(project_dir)

        assert os.path.isfile(legacy_db)
