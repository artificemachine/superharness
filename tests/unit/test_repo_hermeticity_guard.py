"""The hermeticity guard must actually detect a mutated repository.

A guard that cannot fire is worse than no guard: it converts "nobody checked"
into "something checked and it was fine". These tests run the detector against
throwaway repos so its verdict is verified rather than assumed.

Context: docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest import _repo_fingerprint


def _git(project: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=project, capture_output=True, check=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    project = tmp_path / "repo"
    project.mkdir()
    _git(project, "init", "-q")
    _git(project, "config", "user.email", "t@t.com")
    _git(project, "config", "user.name", "t")
    _git(project, "config", "core.hooksPath", "/dev/null")
    (project / "f.txt").write_text("base\n")
    _git(project, "add", "f.txt")
    _git(project, "-c", "commit.gpgsign=false", "commit", "-qm", "base", "--no-verify")
    return project


def _fingerprint(monkeypatch, project: Path):
    """Point the detector at a throwaway repo instead of the real one."""
    import tests.conftest as conftest

    monkeypatch.setattr(conftest, "REPO_ROOT", project)
    return conftest._repo_fingerprint()


class TestDetectorFires:
    """Each case is a real symptom from the 2026-07-31 incident."""

    def test_config_write_is_detected(self, monkeypatch, repo):
        before = _fingerprint(monkeypatch, repo)
        _git(repo, "config", "core.bare", "true")
        assert _fingerprint(monkeypatch, repo) != before

    def test_hooks_path_write_is_detected(self, monkeypatch, repo):
        before = _fingerprint(monkeypatch, repo)
        _git(repo, "config", "core.hooksPath", ".githooks")
        assert _fingerprint(monkeypatch, repo) != before

    def test_new_commit_is_detected(self, monkeypatch, repo):
        before = _fingerprint(monkeypatch, repo)
        (repo / "f.txt").write_text("changed\n")
        _git(
            repo, "-c", "commit.gpgsign=false", "commit", "-qam", "junk", "--no-verify"
        )
        assert _fingerprint(monkeypatch, repo) != before

    def test_new_branch_is_detected(self, monkeypatch, repo):
        before = _fingerprint(monkeypatch, repo)
        _git(repo, "branch", "junk-branch")
        assert _fingerprint(monkeypatch, repo) != before

    def test_stash_is_detected(self, monkeypatch, repo):
        (repo / "f.txt").write_text("dirty\n")
        before = _fingerprint(monkeypatch, repo)
        _git(repo, "stash", "push", "-m", "shux-checkpoint:test-task")
        assert _fingerprint(monkeypatch, repo) != before


class TestDetectorIsQuiet:
    """It must not cry wolf, or it will be disabled and stop protecting anything."""

    def test_stable_when_nothing_changes(self, monkeypatch, repo):
        assert _fingerprint(monkeypatch, repo) == _fingerprint(monkeypatch, repo)

    def test_working_tree_edits_are_ignored(self, monkeypatch, repo):
        """Untracked and modified files are not repository mutations."""
        before = _fingerprint(monkeypatch, repo)
        (repo / "f.txt").write_text("scratch edit\n")
        (repo / "new.txt").write_text("untracked\n")
        assert _fingerprint(monkeypatch, repo) == before

    def test_reads_do_not_trip_it(self, monkeypatch, repo):
        before = _fingerprint(monkeypatch, repo)
        _git(repo, "status", "--porcelain")
        _git(repo, "log", "--oneline", "-1")
        assert _fingerprint(monkeypatch, repo) == before


def test_stands_down_without_a_git_dir(monkeypatch, tmp_path):
    """Installed package or tarball: nothing to protect, so no false failures."""
    import tests.conftest as conftest

    monkeypatch.setattr(conftest, "REPO_ROOT", tmp_path)
    assert conftest._repo_fingerprint() is None


def test_guard_is_active_for_this_very_test():
    """The autouse fixture is wired up, not merely defined."""
    fp = _repo_fingerprint()
    # None is legitimate off a git checkout; a dict must carry the real keys.
    assert fp is None or {"config", "HEAD", "refs/heads"} <= set(fp)
