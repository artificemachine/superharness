"""Regression test for t-842298: watcher-worker must reject --worker that
resolves to the same path as --project.

Without the guard, the command treats the source project as its own worker
directory: it runs a self ``rsync -a --delete``, then deletes the project's
real ``.superharness`` directory and replaces it with a broken self-symlink,
before installing a watcher service against the source project itself.
"""

# Pytest adds src/ via pyproject.toml; this nested worktree is analyzed from the primary root.
# pyright: reportMissingImports=false
from __future__ import annotations

import pytest

from superharness.commands import watcher_worker
from superharness.engine import platform_runtime, service_installer


def _stub_side_effects(monkeypatch):
    sync_calls = []
    install_calls = []
    monkeypatch.setattr(
        platform_runtime,
        "sync_worker_copy",
        lambda *args, **kwargs: sync_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        service_installer,
        "install",
        lambda **kwargs: install_calls.append(kwargs) or False,
    )
    return sync_calls, install_calls


def test_worker_resolving_to_project_rejected_before_mutation(tmp_path, monkeypatch):
    project = tmp_path / "myproject"
    sentinel = project / ".superharness"
    sentinel.mkdir(parents=True)
    sentinel_file = sentinel / "watcher.yaml"
    sentinel_file.write_text("watcher_project: \"original\"\n", encoding="utf-8")
    marker = project / "important.txt"
    marker.write_text("keep me\n", encoding="utf-8")

    # Isolate the regression from rsync and OS service installation.
    sync_calls, install_calls = _stub_side_effects(monkeypatch)

    with pytest.raises(SystemExit) as exc:
        watcher_worker.main(["-p", str(project), "-w", str(project)])

    code = exc.value.code
    assert code != 0, "overlapping --worker/--project must exit non-zero"
    # The rejection must happen BEFORE any mutation: the real .superharness
    # directory (not a self-symlink) must still be there with its content.
    assert sentinel.is_dir() and not sentinel.is_symlink(), (
        ".superharness must remain the real directory; "
        f"got symlink={sentinel.is_symlink()} dir={sentinel.is_dir()}"
    )
    assert sentinel_file.is_file()
    assert sentinel_file.read_text(encoding="utf-8") == "watcher_project: \"original\"\n"
    # No project content may be lost by a self sync either.
    assert marker.read_text(encoding="utf-8") == "keep me\n"
    assert not sync_calls, "overlapping paths must be rejected before sync"
    assert not install_calls, "overlapping paths must be rejected before service install"


def test_worker_overlap_via_dotted_path_rejected(tmp_path, monkeypatch):
    """Same path spelled differently (trailing ``.``) must be caught by
    resolved-path equality, not string equality."""
    project = tmp_path / "proj"
    sentinel = project / ".superharness"
    sentinel.mkdir(parents=True)
    (sentinel / "watcher.yaml").write_text("x: 1\n", encoding="utf-8")

    overlapping = str(project / ".")  # resolves to the same path
    sync_calls, install_calls = _stub_side_effects(monkeypatch)

    # --worker resolves to the same path as --project.
    with pytest.raises(SystemExit) as exc:
        watcher_worker.main(["-p", str(project), "-w", overlapping])

    assert exc.value.code != 0
    assert sentinel.is_dir() and not sentinel.is_symlink()
    assert (sentinel / "watcher.yaml").is_file()
    assert not sync_calls
    assert not install_calls
