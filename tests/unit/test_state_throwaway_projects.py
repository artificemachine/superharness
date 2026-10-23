"""BUG-2026-10-23: throwaway projects must not leave a permanent state directory.

A project that lives under the OS temp directory and has no state yet keeps its
state inside its own `.superharness/`, so the state is removed with the project.
Explicit state configuration and projects outside the temp tree are unchanged.
"""

import os
import tempfile
from pathlib import Path

import pytest

from superharness.engine.db import get_connection
from superharness.utils.paths import (
    resolve_active_state_db_path,
    resolve_xdg_state_db_path,
)


@pytest.fixture
def ambient_home(tmp_path, monkeypatch):
    """Ambient defaults: no explicit state root, HOME pointing at a scratch dir."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("SUPERHARNESS_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("SUPERHARNESS_STATE_PROJECT", raising=False)
    return home


def _legacy(project: Path) -> str:
    return str(project / ".superharness" / "state.sqlite3")


def test_new_temp_project_keeps_state_inside_the_project(ambient_home, tmp_path):
    project = tmp_path / "scratch-project"
    project.mkdir()

    assert resolve_active_state_db_path(str(project)) == _legacy(project.resolve())


def test_temp_project_opening_a_connection_creates_no_permanent_state_dir(
    ambient_home, tmp_path
):
    project = tmp_path / "scratch-project"
    project.mkdir()

    get_connection(str(project)).close()

    assert not (ambient_home / ".local" / "state" / "superharness").exists()
    assert os.path.isfile(_legacy(project.resolve()))


def test_project_outside_the_temp_tree_keeps_the_permanent_state_dir(
    ambient_home, tmp_path, monkeypatch
):
    other_temp = tmp_path / "other-temp-root"
    other_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(other_temp))
    project = tmp_path / "real-project"
    project.mkdir()

    assert resolve_active_state_db_path(str(project)) == resolve_xdg_state_db_path(
        str(project.resolve())
    )


def test_explicit_xdg_state_home_is_honoured_for_temp_projects(
    ambient_home, tmp_path, monkeypatch
):
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg))
    project = tmp_path / "scratch-project"
    project.mkdir()

    assert resolve_active_state_db_path(str(project)) == resolve_xdg_state_db_path(
        str(project.resolve())
    )


def test_explicit_state_dir_is_honoured_for_temp_projects(
    ambient_home, tmp_path, monkeypatch
):
    state = tmp_path / "explicit-state"
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state))
    project = tmp_path / "scratch-project"
    project.mkdir()

    assert resolve_active_state_db_path(str(project)) == resolve_xdg_state_db_path(
        str(project.resolve())
    )


def test_existing_xdg_database_still_wins_for_temp_projects(ambient_home, tmp_path):
    project = tmp_path / "scratch-project"
    project.mkdir()
    xdg_db = Path(resolve_xdg_state_db_path(str(project.resolve())))
    xdg_db.parent.mkdir(parents=True)
    xdg_db.write_bytes(b"")

    assert resolve_active_state_db_path(str(project)) == str(xdg_db)


def test_dispatch_worktree_in_temp_maps_to_the_original_project(
    ambient_home, tmp_path, monkeypatch
):
    other_temp = tmp_path / "other-temp-root"
    other_temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(other_temp))
    original = tmp_path / "original-project"
    original.mkdir()
    worktree = other_temp / "worktree"
    worktree.mkdir()
    monkeypatch.setenv("SUPERHARNESS_STATE_PROJECT", str(original))

    assert resolve_active_state_db_path(str(worktree)) == resolve_xdg_state_db_path(
        str(original.resolve())
    )


def test_shux_init_in_a_temp_project_creates_no_permanent_state_dir(
    ambient_home, tmp_path, repo_root
) -> None:
    import subprocess
    import sys

    project = tmp_path / "scratch-project"
    project.mkdir()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "src")
    env["HOME"] = str(ambient_home)
    for name in ("XDG_STATE_HOME", "SUPERHARNESS_STATE_DIR", "SUPERHARNESS_STATE_PROJECT"):
        env.pop(name, None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "superharness.commands.init_project",
            "--skip-hooks",
            "Scratch",
            "Python",
            "active",
        ],
        cwd=str(project),
        text=True,
        capture_output=True,
        env=env,
        input="",
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (ambient_home / ".local" / "state" / "superharness").exists()
    assert os.path.isfile(_legacy(project.resolve()))
