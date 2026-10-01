"""Regression guards for BUG-2026-09-24.

`shux dashboard` auto-fired `watcher_start` passing the project directory
itself as `--worker`; `watcher_worker` then `rmtree`d the project's real
`.superharness` and created a self-referential symlink. These tests pin the
two guards: worker/project disjointness, and deletion fenced to the
dedicated worker root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from superharness.commands import watcher_worker


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    """A minimal project whose .superharness holds a marker we must survive."""
    proj = tmp_path / "proj"
    (proj / ".superharness").mkdir(parents=True)
    (proj / ".superharness" / "contract.md").write_text("keep", encoding="utf-8")
    return proj


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate Path.home() so the dedicated worker root lands under tmp."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _stale_real_worker_superharness(worker: Path) -> Path:
    """A worker dir holding a REAL .superharness dir (not a symlink)."""
    stale = worker / ".superharness"
    stale.mkdir(parents=True)
    (stale / "stale-state.md").write_text("old", encoding="utf-8")
    return stale


def test_refuses_worker_equal_to_project(project: Path, fake_home: Path):
    """The incident: --worker == project must refuse and not touch .superharness."""
    with pytest.raises(SystemExit):
        watcher_worker.main(["--project", str(project), "--worker", str(project)])
    sh = project / ".superharness"
    assert sh.is_dir() and not sh.is_symlink()
    assert (sh / "contract.md").read_text(encoding="utf-8") == "keep"


def test_refuses_worker_inside_project(project: Path, fake_home: Path):
    nested = project / "nested-worker"
    with pytest.raises(SystemExit):
        watcher_worker.main(["--project", str(project), "--worker", str(nested)])
    assert (project / ".superharness" / "contract.md").exists()


def test_refuses_worker_containing_project(project: Path, tmp_path: Path, fake_home: Path):
    container = tmp_path / "container"
    container.mkdir()
    moved = container / "proj"
    project.rename(moved)  # project now lives INSIDE the worker dir
    with pytest.raises(SystemExit):
        watcher_worker.main(["--project", str(moved), "--worker", str(container)])
    assert (moved / ".superharness" / "contract.md").exists()


def test_refuses_rmtree_outside_dedicated_root(project: Path, tmp_path: Path, fake_home: Path):
    """A real .superharness in a worker OUTSIDE the dedicated worker root is never deleted."""
    worker = tmp_path / "random-worker"
    stale = _stale_real_worker_superharness(worker)
    with pytest.raises(SystemExit):
        watcher_worker.main(["--project", str(project), "--worker", str(worker)])
    assert (stale / "stale-state.md").exists(), "deletion fence violated outside dedicated root"


def test_dedicated_root_stale_worker_dir_replaced(
    project: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """Under the dedicated root the refresh path still works: stale real dir
    is replaced by a symlink to the project's .superharness."""

    def _fake_install(**_kwargs):
        return True

    monkeypatch.setattr("superharness.engine.service_installer.install", _fake_install)
    monkeypatch.setattr("superharness.engine.runtime_probe.probe_runtime", lambda: None)
    monkeypatch.setattr("superharness.engine.runtime_probe.persist_runtime", lambda *a: None)

    worker = fake_home / ".superharness-workers" / project.name
    _stale_real_worker_superharness(worker)

    watcher_worker.main(["--project", str(project), "--worker", str(worker)])

    sh_link = worker / ".superharness"
    assert sh_link.is_symlink()
    assert Path(str(sh_link).replace("\\", "/")).resolve() == (project / ".superharness").resolve()
    assert not (worker / ".superharness" / "stale-state.md").exists()
    # the project's real state was never touched
    assert (project / ".superharness" / "contract.md").read_text(encoding="utf-8") == "keep"


@pytest.fixture(autouse=True)
def isolate_service_install(monkeypatch):
    monkeypatch.setattr("superharness.engine.service_installer.install", lambda **kwargs: True)
    monkeypatch.setattr("superharness.engine.runtime_probe.probe_runtime", lambda: None)
    monkeypatch.setattr("superharness.engine.runtime_probe.persist_runtime", lambda *args: None)


def test_refuses_default_worker_symlink_to_project(project, fake_home):
    worker = fake_home / ".superharness-workers" / project.name
    worker.parent.mkdir()
    worker.symlink_to(project, target_is_directory=True)
    with pytest.raises(SystemExit, match="overlap"):
        watcher_worker.main(["--project", str(project)])
    assert (project / ".superharness" / "contract.md").read_text() == "keep"


def test_refuses_worker_containing_resolved_source_state(project, fake_home):
    worker = fake_home / ".superharness-workers" / project.name
    state = worker / ".superharness"
    state.mkdir(parents=True)
    (state / "state.sqlite3").write_text("keep")
    original = project / ".superharness"
    (original / "contract.md").unlink()
    original.rmdir()
    original.symlink_to(state, target_is_directory=True)
    with pytest.raises(SystemExit, match="overlap"):
        watcher_worker.main(["--project", str(project)])
    assert (state / "state.sqlite3").read_text() == "keep"


def test_refuses_worker_nested_in_resolved_source_state(project, fake_home, tmp_path):
    state = tmp_path / "external" / "state"
    worker = state / "archive"
    marker = worker / "node_modules" / "marker"
    marker.parent.mkdir(parents=True)
    marker.write_text("keep")
    original = project / ".superharness"
    (original / "contract.md").unlink()
    original.rmdir()
    original.symlink_to(state, target_is_directory=True)
    with pytest.raises(SystemExit, match="overlap"):
        watcher_worker.main(["--project", str(project), "--worker", str(worker)])
    assert marker.read_text() == "keep"
