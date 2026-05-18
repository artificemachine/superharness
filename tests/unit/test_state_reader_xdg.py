"""Tests for _has_sqlite_db XDG awareness — Iteration 5, state isolation."""
from __future__ import annotations

import os
import sqlite3

import pytest

from superharness.utils.paths import resolve_xdg_state_db_path


def _touch_db(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS _dummy (id INTEGER PRIMARY KEY)")
    conn.close()


def test_has_sqlite_db_true_when_xdg_path_exists(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "proj")
    os.makedirs(project)
    _touch_db(resolve_xdg_state_db_path(project))

    from superharness.engine.state_reader import _has_sqlite_db
    assert _has_sqlite_db(project) is True


def test_has_sqlite_db_true_when_legacy_path_exists(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "proj")
    legacy = os.path.join(project, ".superharness", "state.sqlite3")
    _touch_db(legacy)

    from superharness.engine.state_reader import _has_sqlite_db
    assert _has_sqlite_db(project) is True


def test_has_sqlite_db_false_when_neither_exists(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)

    project = str(tmp_path / "proj")
    os.makedirs(project)

    from superharness.engine.state_reader import _has_sqlite_db
    assert _has_sqlite_db(project) is False
