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
    resolve_state_dir,
    resolve_config_dir,
    project_hash,
    resolve_xdg_state_db_path,
    is_project_initialized,
    resolve_active_state_db_path,
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


def test_state_db_path_delegates_to_active_resolver(tmp_path):
    # resolve_state_db_path is now a thin wrapper around resolve_active_state_db_path.
    # With no db on disk, both return the XDG path.
    assert resolve_state_db_path(str(tmp_path)) == resolve_active_state_db_path(str(tmp_path))


def test_state_db_path_trailing_slash_normalised(tmp_path):
    # Trailing slash must not produce a different hash than without.
    without = resolve_state_db_path(str(tmp_path))
    with_slash = resolve_state_db_path(str(tmp_path) + "/")
    assert without == with_slash


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


# ---------------------------------------------------------------------------
# XDG state / config dir resolution (Iteration 1 — BUG-11 / state isolation)
# ---------------------------------------------------------------------------

def test_state_dir_default_xdg(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    result = resolve_state_dir()
    expected = os.path.join(os.path.expanduser("~"), ".local", "state", "superharness")
    assert result == expected


def test_state_dir_env_override_SUPERHARNESS_STATE_DIR(monkeypatch, tmp_path):
    override = str(tmp_path / "sh_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", override)
    assert resolve_state_dir() == override


def test_config_dir_default_xdg(monkeypatch):
    monkeypatch.delenv("SUPERHARNESS_CONFIG_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    result = resolve_config_dir()
    expected = os.path.join(os.path.expanduser("~"), ".config", "superharness")
    assert result == expected


def test_project_hash_stable_for_same_worktree(tmp_path):
    project_dir = str(tmp_path)
    first = project_hash(project_dir)
    second = project_hash(project_dir)
    assert first == second
    assert len(first) == 12  # short hex digest for human-readable paths


def test_project_hash_differs_for_two_worktrees(tmp_path):
    wt1 = str(tmp_path / "repo-worktree-1")
    wt2 = str(tmp_path / "repo-worktree-2")
    assert project_hash(wt1) != project_hash(wt2)


# ---------------------------------------------------------------------------
# XDG state db path (Iteration 2 — out-of-repo state.db location)
# ---------------------------------------------------------------------------

def test_xdg_state_db_path_default_structure(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    project_dir = str(tmp_path / "myproject")
    result = resolve_xdg_state_db_path(project_dir)
    state_dir = os.path.join(os.path.expanduser("~"), ".local", "state", "superharness")
    phash = project_hash(project_dir)
    expected = os.path.join(state_dir, phash, "state.db")
    assert result == expected


def test_xdg_state_db_path_env_override_state_dir(monkeypatch, tmp_path):
    override = str(tmp_path / "sh_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", override)
    project_dir = str(tmp_path / "myproject")
    result = resolve_xdg_state_db_path(project_dir)
    phash = project_hash(project_dir)
    assert result == os.path.join(override, phash, "state.db")


def test_xdg_state_db_path_isolation_across_projects(monkeypatch, tmp_path):
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    proj_a = str(tmp_path / "project-alpha")
    proj_b = str(tmp_path / "project-beta")
    assert resolve_xdg_state_db_path(proj_a) != resolve_xdg_state_db_path(proj_b)


# ---------------------------------------------------------------------------
# is_project_initialized (Iteration 6 — public guard for command entry points)
# ---------------------------------------------------------------------------

def test_is_project_initialized_true_when_xdg_db_exists(monkeypatch, tmp_path):
    import sqlite3 as _sqlite3
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    os.makedirs(project)
    db_path = resolve_xdg_state_db_path(project)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    _sqlite3.connect(db_path).close()
    assert is_project_initialized(project) is True


def test_is_project_initialized_true_when_legacy_db_exists(monkeypatch, tmp_path):
    import sqlite3 as _sqlite3
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    legacy = os.path.join(project, ".superharness", "state.sqlite3")
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    _sqlite3.connect(legacy).close()
    assert is_project_initialized(project) is True


def test_is_project_initialized_false_when_no_db(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    os.makedirs(project)
    assert is_project_initialized(project) is False


# ---------------------------------------------------------------------------
# resolve_active_state_db_path (Iteration 7 — single unified path resolver)
# ---------------------------------------------------------------------------

def test_resolve_active_state_db_path_returns_xdg_when_xdg_exists(monkeypatch, tmp_path):
    import sqlite3 as _sqlite3
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    xdg_path = resolve_xdg_state_db_path(project)
    os.makedirs(os.path.dirname(xdg_path), exist_ok=True)
    _sqlite3.connect(xdg_path).close()
    assert resolve_active_state_db_path(project) == xdg_path


def test_resolve_active_state_db_path_returns_legacy_when_only_legacy_exists(monkeypatch, tmp_path):
    import sqlite3 as _sqlite3
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    legacy = os.path.join(project, ".superharness", "state.sqlite3")
    os.makedirs(os.path.dirname(legacy), exist_ok=True)
    _sqlite3.connect(legacy).close()
    assert resolve_active_state_db_path(project) == legacy


def test_resolve_active_state_db_path_returns_xdg_for_new_project(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    # No XDG, no legacy, no .superharness/ dir — truly new project → XDG
    expected = resolve_xdg_state_db_path(project)
    assert resolve_active_state_db_path(project) == expected


def test_resolve_active_state_db_path_returns_legacy_when_sh_dir_exists(monkeypatch, tmp_path):
    state_dir = str(tmp_path / "xdg_state_empty")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    # .superharness/ dir exists but no db yet — backward-compat with shux init
    os.makedirs(os.path.join(project, ".superharness"))
    expected = os.path.join(project, ".superharness", "state.sqlite3")
    assert resolve_active_state_db_path(project) == expected


# ── Iter 12 RED: resolve_state_db_path must delegate to resolve_active_state_db_path ─

def test_single_resolver_of_record_footgun_redirected(tmp_path, monkeypatch):
    """resolve_state_db_path must return the same result as resolve_active_state_db_path.

    RED: currently resolve_state_db_path is a footgun that always returns the
    legacy .superharness/state.sqlite3 path, ignoring XDG state and env overrides.
    GREEN: redirect it to resolve_active_state_db_path so there is one resolver of record.
    """
    state_dir = str(tmp_path / "xdg_state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", state_dir)
    project = str(tmp_path / "proj")
    # XDG db exists — active resolver should return XDG, not legacy
    xdg_path = resolve_xdg_state_db_path(project)
    os.makedirs(os.path.dirname(xdg_path), exist_ok=True)
    open(xdg_path, "w").close()

    result = resolve_state_db_path(project)
    assert result == xdg_path, (
        f"resolve_state_db_path returned {result!r} (footgun legacy path) "
        f"instead of the active XDG path {xdg_path!r}. "
        "Redirect resolve_state_db_path → resolve_active_state_db_path."
    )
