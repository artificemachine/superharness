"""Regression tests for 2026-07-09: the test suite leaked SQLite state into the
user's real XDG state directory, making runs history-dependent and flaky.

Root cause (reproduced deterministically):

`get_connection(project_dir)` resolves the database to
`<state_dir>/<sha256(abspath(project_dir))[:12]>/state.db`, where `state_dir`
defaults to `~/.local/state/superharness`. That path lives **outside** the
project directory and persists indefinitely.

pytest's `tmp_path` lives under the OS temp root, which macOS purges
periodically. When it is purged, pytest's `pytest-N` counter restarts, so a
later run hands a test the *same* `tmp_path` string it used weeks earlier. The
XDG state dir keyed on that path still exists, so a "fresh" `tmp_path` silently
reopens a stale database full of rows from the earlier run. Any test that
inserts a fixed primary key then dies with
`sqlite3.IntegrityError: UNIQUE constraint failed: inbox.id`.

Observed as a ~1-in-4 flake in `TestAgentAvailabilityScope` on `main` with no
changes, and as 30k+ accumulated directories under the user's real
`~/.local/state/superharness/`.

Fix: an autouse fixture points `SUPERHARNESS_STATE_DIR` at a per-test temporary
directory, so state is isolated per test and nothing escapes into `$HOME`.
"""
from __future__ import annotations

import os
from pathlib import Path

from superharness.utils.paths import resolve_state_dir, resolve_xdg_state_db_path


def _real_home_state_dir() -> Path:
    return Path.home() / ".local" / "state" / "superharness"


def test_state_dir_is_isolated_from_the_real_home_directory():
    """The suite must never resolve state into the user's real XDG directory."""
    resolved = Path(resolve_state_dir()).resolve()
    real = _real_home_state_dir().resolve()
    assert resolved != real, (
        f"tests are writing SQLite state into the user's real state dir: {resolved}"
    )
    assert real not in resolved.parents, (
        f"tests are writing SQLite state under the user's real state dir: {resolved}"
    )


def test_project_db_path_lives_under_the_isolated_state_dir(tmp_path):
    """A project's resolved db must sit inside the isolated state dir, so it
    cannot survive the test that created it."""
    db_path = Path(resolve_xdg_state_db_path(str(tmp_path))).resolve()
    state_dir = Path(resolve_state_dir()).resolve()
    assert state_dir in db_path.parents, (
        f"db {db_path} is not under the isolated state dir {state_dir}"
    )


def test_state_dir_env_var_is_set_for_subprocesses():
    """Tests spawn `python -m superharness...` subprocesses; they inherit os.environ,
    so the isolation must live in the environment, not only in-process."""
    assert os.environ.get("SUPERHARNESS_STATE_DIR"), (
        "SUPERHARNESS_STATE_DIR must be exported so subprocess tests are isolated too"
    )


def test_fresh_project_dir_sees_no_stale_rows(tmp_path):
    """The exact failure mode: a project dir that a previous run already used must
    not resurrect that run's rows."""
    from superharness.engine.db import get_connection, init_db

    project = tmp_path / "proj"
    project.mkdir()

    conn = get_connection(str(project))
    init_db(conn, project_dir=str(project))
    count = conn.execute("SELECT COUNT(*) FROM inbox").fetchone()[0]
    conn.close()

    assert count == 0, (
        f"a fresh project dir opened a database with {count} pre-existing inbox rows"
    )
