"""Tests for engine.launchd_health — operator self-heal + cleanup.

All launchctl interactions are mocked so the test suite runs
identically on macOS and Linux. Real-world coverage of the bootstrap
path comes from the manual smoke test in operator install.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def force_macos(monkeypatch):
    monkeypatch.setattr(
        "superharness.engine.launchd_health.platform.system",
        lambda: "Darwin",
    )


@pytest.fixture
def isolated_launch_agents(tmp_path, monkeypatch):
    """Point _launch_agents_dir() at a tmp dir so the test never
    touches the user's real ~/Library/LaunchAgents."""
    fake_home = tmp_path / "home"
    (fake_home / "Library" / "LaunchAgents").mkdir(parents=True)
    monkeypatch.setattr(
        "superharness.engine.launchd_health.Path.home",
        classmethod(lambda cls: fake_home),
    )
    return fake_home / "Library" / "LaunchAgents"


# ---------------------------------------------------------------------------
# list_loaded_superharness_services
# ---------------------------------------------------------------------------


_FAKE_LAUNCHCTL_LIST = (
    "PID\tStatus\tLabel\n"
    "12345\t0\tcom.superharness.operator.deadbeef\n"
    "-\t1\tcom.superharness.inbox.worker-proj\n"
    "-\t1\tcom.superharness.inbox.worker-proj-custom\n"
    "67890\t0\tcom.apple.something.else\n"
)


class TestListLoaded:
    def test_skips_non_macos(self, monkeypatch):
        from superharness.engine import launchd_health
        monkeypatch.setattr(launchd_health.platform, "system", lambda: "Linux")
        assert launchd_health.list_loaded_superharness_services() == []

    def test_parses_launchctl_output(self, force_macos):
        from superharness.engine import launchd_health
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_FAKE_LAUNCHCTL_LIST, stderr="",
        )
        with mock.patch.object(launchd_health, "_run", return_value=fake):
            entries = launchd_health.list_loaded_superharness_services()
        labels = [e.label for e in entries]
        assert labels == [
            "com.superharness.operator.deadbeef",
            "com.superharness.inbox.worker-proj",
            "com.superharness.inbox.worker-proj-custom",
        ]
        assert entries[0].pid == 12345
        assert entries[1].pid is None
        assert entries[1].last_exit_code == 1


# ---------------------------------------------------------------------------
# find_zombies, find_stale_versions, find_orphan_plists
# ---------------------------------------------------------------------------


class TestFindZombies:
    def test_zombie_is_loaded_with_no_plist(self, force_macos, isolated_launch_agents):
        from superharness.engine import launchd_health

        # Only the operator plist exists on disk
        (isolated_launch_agents / "com.superharness.operator.deadbeef.plist").write_text("")

        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_FAKE_LAUNCHCTL_LIST, stderr="",
        )
        with mock.patch.object(launchd_health, "_run", return_value=fake):
            zombies = launchd_health.find_zombies()
        zombie_labels = sorted(z.label for z in zombies)
        # Both worker-proj entries are zombies (no plist), operator is not.
        assert zombie_labels == [
            "com.superharness.inbox.worker-proj",
            "com.superharness.inbox.worker-proj-custom",
        ]


class TestFindStaleVersions:
    def test_inbox_pattern_is_stale(self, force_macos):
        from superharness.engine import launchd_health
        fake = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_FAKE_LAUNCHCTL_LIST, stderr="",
        )
        with mock.patch.object(launchd_health, "_run", return_value=fake):
            stale = launchd_health.find_stale_versions()
        assert {s.label for s in stale} == {
            "com.superharness.inbox.worker-proj",
            "com.superharness.inbox.worker-proj-custom",
        }


class TestFindOrphanPlists:
    def test_returns_stale_pattern_plists_on_disk(self, force_macos, isolated_launch_agents):
        from superharness.engine import launchd_health
        (isolated_launch_agents / "com.superharness.inbox.old1.plist").write_text("")
        (isolated_launch_agents / "com.superharness.watcher.old2.plist").write_text("")
        (isolated_launch_agents / "com.superharness.operator.live.plist").write_text("")
        orphans = launchd_health.find_orphan_plists()
        names = sorted(p.name for p in orphans)
        assert names == [
            "com.superharness.inbox.old1.plist",
            "com.superharness.watcher.old2.plist",
        ]


# ---------------------------------------------------------------------------
# heal — full self-repair pass
# ---------------------------------------------------------------------------


class TestHeal:
    def test_non_macos_returns_skipped_report(self, monkeypatch):
        from superharness.engine import launchd_health
        monkeypatch.setattr(launchd_health.platform, "system", lambda: "Linux")
        report = launchd_health.heal(operator_plist=None)
        assert report.skipped_reason == "not macOS"
        assert report.fixed_count() == 0

    def test_full_repair_pass(self, force_macos, isolated_launch_agents):
        from superharness.engine import launchd_health

        # Seed: operator plist exists on disk (not loaded), and two
        # zombie inbox.* entries are loaded with no backing plists, and
        # one orphan stale plist exists on disk too.
        op_plist = isolated_launch_agents / "com.superharness.operator.live.plist"
        op_plist.write_text("")
        (isolated_launch_agents / "com.superharness.inbox.orphan.plist").write_text("")

        list_output = (
            "PID\tStatus\tLabel\n"
            "-\t1\tcom.superharness.inbox.worker-proj\n"
            "-\t1\tcom.superharness.inbox.worker-proj-custom\n"
            # operator NOT loaded — so heal must bootstrap it.
        )

        call_log: list[list[str]] = []

        def fake_run(cmd, *, timeout=5.0):
            call_log.append(list(cmd))
            if cmd[:2] == ["launchctl", "list"] and len(cmd) == 2:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=list_output, stderr="")
            if cmd[:2] == ["launchctl", "list"] and len(cmd) == 3:
                # `launchctl list <label>` — is_loaded check.
                # Return 0 only after bootstrap was called for that label.
                label = cmd[2]
                bootstrapped = any(
                    c[:2] == ["launchctl", "bootstrap"] and c[-1].endswith(f"{label}.plist")
                    for c in call_log
                )
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0 if bootstrapped else 1, stdout="", stderr="",
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with mock.patch.object(launchd_health, "_run", side_effect=fake_run):
            report = launchd_health.heal(operator_plist=op_plist)

        # Both zombies were bootout'd as zombies (loaded + no plist).
        # The stale-pattern check runs second and finds nothing new
        # because they've been removed from the launchctl list view
        # (actually the second `list` happens before heal calls bootout
        # — so it still sees them as stale). The dedup happens because
        # find_stale_versions and find_zombies both query, and bootout
        # is idempotent.
        assert set(report.zombies_removed) >= {
            "com.superharness.inbox.worker-proj",
            "com.superharness.inbox.worker-proj-custom",
        }
        # Orphan stale-pattern plist on disk was removed.
        assert report.orphan_plists_removed == ["com.superharness.inbox.orphan.plist"]
        # Operator plist was bootstrapped.
        assert report.bootstrapped == ["com.superharness.operator.live"]
        # The orphan plist was actually unlinked from disk.
        assert not (isolated_launch_agents / "com.superharness.inbox.orphan.plist").is_file()

    def test_nothing_to_do_returns_clean_report(self, force_macos, isolated_launch_agents):
        from superharness.engine import launchd_health

        op_plist = isolated_launch_agents / "com.superharness.operator.live.plist"
        op_plist.write_text("")

        list_output = (
            "PID\tStatus\tLabel\n"
            "12345\t0\tcom.superharness.operator.live\n"  # already loaded
        )

        def fake_run(cmd, *, timeout=5.0):
            if cmd[:2] == ["launchctl", "list"] and len(cmd) == 3:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=list_output, stderr="")

        with mock.patch.object(launchd_health, "_run", side_effect=fake_run):
            report = launchd_health.heal(operator_plist=op_plist)

        assert report.fixed_count() == 0
        assert report.summary() == "launchd-heal: nothing to do (state is clean)"


# ---------------------------------------------------------------------------
# watchdog plist write
# ---------------------------------------------------------------------------


class TestWatchdogPlist:
    def test_write_watchdog_plist_creates_file_with_expected_keys(
        self, force_macos, isolated_launch_agents,
    ):
        from superharness.engine import launchd_health
        wp = launchd_health.write_watchdog_plist(python_bin="/usr/bin/python3", interval_seconds=300)
        assert wp.is_file()
        content = wp.read_text()
        assert "<key>Label</key>" in content
        assert "com.superharness.operator-watchdog" in content
        assert "<string>heal</string>" in content
        assert "<string>--auto-discover</string>" in content
        assert "<string>--quiet</string>" in content
        assert "<integer>300</integer>" in content
        # KeepAlive=true so launchd restarts the watchdog if it crashes.
        assert "<key>KeepAlive</key>\n    <true/>" in content
        assert "<key>RunAtLoad</key>\n    <true/>" in content
        assert "<key>WorkingDirectory</key>" in content

    def test_watchdog_uses_custom_interval(self, force_macos, isolated_launch_agents):
        from superharness.engine import launchd_health
        wp = launchd_health.write_watchdog_plist(interval_seconds=120)
        assert "<integer>120</integer>" in wp.read_text()


# ---------------------------------------------------------------------------
# find_all_superharness_projects — TCC-protected directory pruning
# ---------------------------------------------------------------------------


class TestDiscoverySkipsProtectedDirs:
    """Auto-discovery walks $HOME. It must NOT descend into macOS
    TCC-protected home subdirectories (Library, Desktop, Documents,
    Downloads, ...). Entering them trips the "would like to access data
    from other apps" prompt on every 5-min watchdog scan, and they never
    hold legitimate dev projects. (Fix: TCC-prompt-loop-auto-discover.)
    """

    def _make_project(self, home: Path, rel: str) -> Path:
        proj = home / rel
        marker_dir = proj / ".superharness"
        marker_dir.mkdir(parents=True)
        (marker_dir / "persistent").touch()
        return proj.resolve()

    def test_default_home_scan_skips_protected_dirs(self, tmp_path, monkeypatch):
        from superharness.engine import launchd_health

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(
            "superharness.engine.launchd_health.Path.home",
            classmethod(lambda cls: home),
        )

        wanted = self._make_project(home, "DevOpsSec/proj")
        # These live under TCC-protected roots and must be pruned.
        self._make_project(home, "Library/Application Support/proj")
        self._make_project(home, "Documents/proj")
        self._make_project(home, "Desktop/proj")
        self._make_project(home, "Downloads/proj")

        found = launchd_health.find_all_superharness_projects()

        assert wanted in found
        assert all("/Library/" not in str(p) for p in found)
        assert all("/Documents/" not in str(p) for p in found)
        assert all("/Desktop/" not in str(p) for p in found)
        assert all("/Downloads/" not in str(p) for p in found)

    def test_explicit_search_root_is_honored(self, tmp_path, monkeypatch):
        """Pruning applies only to the default $HOME scan. When a caller
        passes search_roots explicitly, respect their intent fully."""
        from superharness.engine import launchd_health

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(
            "superharness.engine.launchd_health.Path.home",
            classmethod(lambda cls: home),
        )
        proj = self._make_project(home, "Documents/proj")

        found = launchd_health.find_all_superharness_projects(
            search_roots=[home / "Documents"],
        )

        assert proj in found
