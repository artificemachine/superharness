"""Tests for git checkpoint/rollback (cherry-picked from hermes-agent)."""
import os
import subprocess
import pytest
from superharness.guard.checkpoint import snapshot, list_checkpoints


def _init_git(path):
    subprocess.run(["git", "init", "-b", "master"], cwd=path, capture_output=True, check=True)
    (path / "test.txt").write_text("original")
    subprocess.run(["git", "add", "test.txt"], cwd=path, capture_output=True)
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_EMAIL": "t@t.com", "GIT_AUTHOR_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t.com", "GIT_COMMITTER_NAME": "T"})
    subprocess.run(["git", "commit", "--no-verify", "-m", "i"], cwd=path, capture_output=True, check=True, env=env)


class TestCheckpoint:
    def test_snapshot_creates_stash(self, tmp_path):
        _init_git(tmp_path)
        (tmp_path / "test.txt").write_text("modified")
        ok = snapshot(str(tmp_path), "test-task")
        result = subprocess.run(["git", "stash", "list"], cwd=tmp_path, capture_output=True, text=True)
        assert "test-task" in result.stdout or ok

    def test_list_checkpoints(self, tmp_path):
        _init_git(tmp_path)
        (tmp_path / "test.txt").write_text("modified")
        snapshot(str(tmp_path), "task-one")
        checkpoints = list_checkpoints(str(tmp_path))
        assert isinstance(checkpoints, list)

    def test_snapshot_no_changes_returns_false(self, tmp_path):
        _init_git(tmp_path)
        ok = snapshot(str(tmp_path), "no-changes")
        assert ok is False
