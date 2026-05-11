"""Tests for superharness.utils.paths.

Env-var based resolution for SUPERHARNESS_DATA_DIR and SUPERHARNESS_DASHBOARD_PORT.
Pure helpers, no I/O. Existing call sites opt in by switching to these
resolvers in follow-up work.
"""
from __future__ import annotations

import os

import pytest

from superharness.utils.paths import (
    resolve_project_dir,
    resolve_state_db_path,
    resolve_dashboard_port,
)


def test_resolve_project_dir_returns_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_DATA_DIR", raising=False)
    assert resolve_project_dir("/tmp/default") == "/tmp/default"


def test_resolve_project_dir_returns_env_when_set(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_DATA_DIR", "/tmp/override")
    assert resolve_project_dir("/tmp/default") == "/tmp/override"


def test_resolve_project_dir_ignores_empty_env(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_DATA_DIR", "")
    assert resolve_project_dir("/tmp/default") == "/tmp/default"


def test_state_db_path_under_project():
    p = resolve_state_db_path("/tmp/proj")
    expected = os.path.join("/tmp/proj", ".superharness", "state.sqlite3")
    assert p == expected


def test_state_db_path_trailing_slash_normalised():
    # Trailing slash (or backslash on Windows) on the project dir should not
    # produce a duplicated separator after the join.
    p = resolve_state_db_path("/tmp/proj/")
    expected = os.path.join("/tmp/proj", ".superharness", "state.sqlite3")
    assert p == expected


def test_dashboard_port_default_when_env_unset(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_DASHBOARD_PORT", raising=False)
    assert resolve_dashboard_port(8787) == 8787


def test_dashboard_port_from_env(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_DASHBOARD_PORT", "9090")
    assert resolve_dashboard_port(8787) == 9090


def test_dashboard_port_rejects_below_range(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_DASHBOARD_PORT", "80")
    with pytest.raises(ValueError):
        resolve_dashboard_port(8787)


def test_dashboard_port_rejects_above_range(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_DASHBOARD_PORT", "70000")
    with pytest.raises(ValueError):
        resolve_dashboard_port(8787)


def test_dashboard_port_rejects_non_numeric(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_DASHBOARD_PORT", "not-a-number")
    with pytest.raises(ValueError):
        resolve_dashboard_port(8787)


def test_dashboard_port_default_validated(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_DASHBOARD_PORT", raising=False)
    with pytest.raises(ValueError):
        resolve_dashboard_port(80)
