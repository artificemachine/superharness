"""heal() must not delete another project's live watcher-worker inbox job.

`shux watcher-worker` writes `com.superharness.inbox.<name>` plists that carry
SUPERHARNESS_STATE_PROJECT. Pre-1.50 legacy inbox jobs do not. `operator install`
for project A replaces A's own inbox job but must leave B's alone.
"""

from __future__ import annotations

import plistlib
from pathlib import Path
from unittest import mock

import pytest

from superharness.engine import launchd_health


@pytest.fixture
def force_macos(monkeypatch):
    monkeypatch.setattr(launchd_health.platform, "system", lambda: "Darwin")


@pytest.fixture
def agents_dir(tmp_path, monkeypatch) -> Path:
    fake_home = tmp_path / "home"
    target = fake_home / "Library" / "LaunchAgents"
    target.mkdir(parents=True)
    monkeypatch.setattr(
        "superharness.engine.launchd_health.Path.home",
        classmethod(lambda cls: fake_home),
    )
    return target


def _write_inbox_plist(agents: Path, name: str, state_project: Path | None) -> str:
    label = f"com.superharness.inbox.{name}"
    body: dict = {"Label": label, "ProgramArguments": ["/bin/true"]}
    if state_project is not None:
        body["EnvironmentVariables"] = {"SUPERHARNESS_STATE_PROJECT": str(state_project)}
    with (agents / f"{label}.plist").open("wb") as fh:
        plistlib.dump(body, fh)
    return label


def test_other_projects_live_inbox_plist_is_spared(force_macos, agents_dir, tmp_path):
    proj_a, proj_b = tmp_path / "a", tmp_path / "b"
    _write_inbox_plist(agents_dir, "b", proj_b)
    assert launchd_health.find_orphan_plists(replacing_project=proj_a) == []


def test_replaced_projects_own_inbox_plist_is_removed(
    force_macos, agents_dir, tmp_path
):
    proj_a = tmp_path / "a"
    label = _write_inbox_plist(agents_dir, "a", proj_a)
    found = launchd_health.find_orphan_plists(replacing_project=proj_a)
    assert [p.stem for p in found] == [label]


def test_legacy_inbox_plist_without_marker_is_still_removed(
    force_macos, agents_dir, tmp_path
):
    label = _write_inbox_plist(agents_dir, "legacy", None)
    found = launchd_health.find_orphan_plists(replacing_project=tmp_path / "a")
    assert [p.stem for p in found] == [label]


def test_no_replacing_project_spares_every_live_inbox_plist(
    force_macos, agents_dir, tmp_path
):
    _write_inbox_plist(agents_dir, "a", tmp_path / "a")
    _write_inbox_plist(agents_dir, "b", tmp_path / "b")
    assert launchd_health.find_orphan_plists() == []


def test_heal_boots_out_only_stale_services(force_macos, agents_dir, tmp_path):
    proj_a, proj_b = tmp_path / "a", tmp_path / "b"
    own = _write_inbox_plist(agents_dir, "a", proj_a)
    other = _write_inbox_plist(agents_dir, "b", proj_b)
    legacy = _write_inbox_plist(agents_dir, "legacy", None)
    loaded = [
        launchd_health.LaunchdEntry(label=label, pid=None, last_exit_code=0)
        for label in (own, other, legacy)
    ]
    with (
        mock.patch.object(
            launchd_health, "list_loaded_superharness_services", return_value=loaded
        ),
        mock.patch.object(launchd_health, "bootout", return_value=True) as bootout,
    ):
        report = launchd_health.heal(replacing_project=proj_a)

    assert sorted(c.args[0] for c in bootout.call_args_list) == sorted([own, legacy])
    assert (agents_dir / f"{other}.plist").is_file()
    assert not (agents_dir / f"{own}.plist").exists()
    assert not (agents_dir / f"{legacy}.plist").exists()
    assert sorted(report.stale_services_removed) == sorted([own, legacy])
