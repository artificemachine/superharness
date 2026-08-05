"""Tests for NFS-aware SQLite journal mode (extracted from PR #77, 2026-08-03).

WAL requires a shared-memory (-shm) mmap that network filesystems (NFS/CIFS)
cannot provide, so concurrent multi-host writers corrupt the database. The
change makes every DB opener resolve the journal mode via
engine.db._resolve_journal_mode: WAL on local disk, a rollback journal
(PERSIST) on network mounts, with a SUPERHARNESS_JOURNAL_MODE override.

Tests are hermetic: _is_network_fs is exercised against a fake /proc/mounts
via monkeypatch (no real NFS mounts on CI runners), and get_connection's
integration path uses the DELETE override (a valid rollback journal) instead
of PERSIST so local-disk test dirs behave deterministically.
"""

from __future__ import annotations

import os
import sqlite3

import pytest


def _make_legacy_db(project_dir: str) -> str:
    sh = os.path.join(project_dir, ".superharness")
    os.makedirs(sh, exist_ok=True)
    db_path = os.path.join(sh, "state.sqlite3")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()
    return db_path


# ---------------------------------------------------------------------------
# _is_network_fs — against a fake /proc/mounts
# ---------------------------------------------------------------------------

_FAKE_MOUNTS = (
    "/dev/disk1s1 / apfs rw,local 0 0\n"
    "/dev/disk3s1 /System/Volumes/Data apfs rw,local 0 0\n"
    "nas:/export /mnt/nas nfs4 rw 0 0\n"
    "smb://server/share /Volumes/share smbfs rw 0 0\n"
    "/dev/sda1 /home ext4 rw 0 0\n"
)


@pytest.fixture
def fake_mounts(monkeypatch, tmp_path):
    """Patch open('/proc/mounts') to a fake table so _is_network_fs is
    deterministic regardless of the host's real mounts."""
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text(_FAKE_MOUNTS)

    real_open = open

    def _open(path, *args, **kwargs):
        if str(path) == "/proc/mounts":
            return real_open(mounts_file, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _open)
    # Windows normalizes POSIX-style paths (drive prefix, backslashes), which
    # breaks the mount-point prefix match. Pin realpath to identity so the
    # target string compares exactly against the fake mount table.
    import superharness.engine.db as db_mod

    monkeypatch.setattr(db_mod.os.path, "realpath", lambda p: p)
    return mounts_file


def test_is_network_fs_true_on_nfs_mount(fake_mounts):
    from superharness.engine.db import _is_network_fs

    assert _is_network_fs("/mnt/nas/shared/state.db") is True


def test_is_network_fs_true_on_smb_mount(fake_mounts):
    from superharness.engine.db import _is_network_fs

    assert _is_network_fs("/Volumes/share/project/state.db") is True


def test_is_network_fs_false_on_local_mount(fake_mounts):
    from superharness.engine.db import _is_network_fs

    assert _is_network_fs("/home/user/project/state.db") is False


def test_is_network_fs_false_without_proc_mounts(monkeypatch, tmp_path):
    """No /proc/mounts (non-Linux host) → False (WAL default preserved)."""
    from superharness.engine.db import _is_network_fs

    real_open = open

    def _open(path, *args, **kwargs):
        if str(path) == "/proc/mounts":
            raise OSError(2, "No such file or directory")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", _open)
    assert _is_network_fs("/some/path/state.db") is False


def test_is_network_fs_resolves_realpath(fake_mounts, tmp_path, monkeypatch):
    """_is_network_fs must realpath() the target so a symlinked path resolves
    to its actual mount."""
    import superharness.engine.db as db_mod

    monkeypatch.setattr(db_mod.os.path, "realpath", lambda p: "/mnt/nas/real/state.db")
    assert db_mod._is_network_fs("/symlink/state.db") is True


# ---------------------------------------------------------------------------
# _resolve_journal_mode — override validation
# ---------------------------------------------------------------------------


def test_resolve_journal_mode_default_wal_on_local(fake_mounts, monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_JOURNAL_MODE", raising=False)
    from superharness.engine.db import _resolve_journal_mode

    assert _resolve_journal_mode("/home/user/proj/state.db") == "WAL"


def test_resolve_journal_mode_persist_on_network(fake_mounts, monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_JOURNAL_MODE", raising=False)
    from superharness.engine.db import _resolve_journal_mode

    assert _resolve_journal_mode("/mnt/nas/proj/state.db") == "PERSIST"


def test_resolve_journal_mode_valid_override_wins(fake_mounts, monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_JOURNAL_MODE", "DELETE")
    from superharness.engine.db import _resolve_journal_mode

    # Even on a network mount the explicit override wins.
    assert _resolve_journal_mode("/mnt/nas/proj/state.db") == "DELETE"


def test_resolve_journal_mode_invalid_override_ignored(fake_mounts, monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_JOURNAL_MODE", "WALMART")
    from superharness.engine.db import _resolve_journal_mode

    # Falls back to the fs-derived default; a typo must not crash or inject.
    assert _resolve_journal_mode("/home/user/proj/state.db") == "WAL"


def test_resolve_journal_mode_override_is_case_insensitive(fake_mounts, monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_JOURNAL_MODE", "delete")
    from superharness.engine.db import _resolve_journal_mode

    assert _resolve_journal_mode("/home/user/proj/state.db") == "DELETE"


# ---------------------------------------------------------------------------
# get_connection integration — journal mode actually applied
# ---------------------------------------------------------------------------


def test_get_connection_applies_override_journal_mode(tmp_path, monkeypatch):
    """A valid override must be applied by get_connection (here: DELETE, a
    rollback journal safe to use on local-disk test dirs)."""
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    monkeypatch.setenv("SUPERHARNESS_JOURNAL_MODE", "DELETE")
    project = str(tmp_path / "proj")
    _make_legacy_db(project)

    from superharness.engine.db import get_connection

    conn = get_connection(project)
    try:
        jm = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        conn.close()

    assert jm == "delete", f"Expected journal_mode=delete, got {jm!r}"
    assert fk == 1


def test_get_connection_removes_stale_sidecars_when_leaving_wal(tmp_path, monkeypatch):
    """Opening in a non-WAL mode must drop stale -wal/-shm sidecars from a
    previous WAL regime BEFORE connecting (a corrupt -wal would otherwise be
    checkpointed into the main DB by the mode change)."""
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    monkeypatch.setenv("SUPERHARNESS_JOURNAL_MODE", "DELETE")
    project = str(tmp_path / "proj")
    db_path = _make_legacy_db(project)

    # Simulate the leftover sidecars of a WAL regime
    for suffix in ("-wal", "-shm"):
        with open(db_path + suffix, "wb") as f:
            f.write(b"stale")

    from superharness.engine.db import get_connection

    conn = get_connection(project)
    conn.close()

    assert not os.path.exists(db_path + "-wal"), "stale -wal must be removed"
    assert not os.path.exists(db_path + "-shm"), "stale -shm must be removed"
