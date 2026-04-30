"""Tests for watcher health check on enqueue."""
from __future__ import annotations

from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite
from unittest.mock import patch

import pytest

from superharness.commands.inbox_enqueue import (
    _check_watcher_health,
    enqueue_cmd,
)


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "test-proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    contract = {
        "id": "C-001",
        "created": "2026-01-01",
        "created_by": "owner",
        "status": "active",
        "tasks": [
            {
                "id": "T-1",
                "title": "Test task",
                "owner": "claude-code",
                "status": "plan_approved",
                "project_path": str(project),
            }
        ],
    }
    import yaml
    (harness / "contract.yaml").write_text(yaml.safe_dump(contract))
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")
    seed_sqlite_from_yaml(project)
    return project


# ---------------------------------------------------------------------------
# _check_watcher_health
# ---------------------------------------------------------------------------


class TestCheckWatcherHealth:
    def test_returns_true_when_watcher_loaded(self, tmp_path):
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue.platform") as mock_plat:
            mock_plat.system.return_value = "Darwin"
            with patch("superharness.commands.inbox_enqueue.subprocess.run") as mock_run:
                mock_run.return_value.stdout = "com.superharness.inbox.test-proj\n"
                assert _check_watcher_health(str(project)) is True

    def test_returns_false_when_watcher_not_loaded(self, tmp_path):
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue.platform") as mock_plat:
            mock_plat.system.return_value = "Darwin"
            with patch("superharness.commands.inbox_enqueue.subprocess.run") as mock_run:
                mock_run.return_value.stdout = "some.other.service\n"
                assert _check_watcher_health(str(project)) is False

    def test_returns_true_on_non_darwin(self, tmp_path):
        """Non-macOS platforms skip launchd check — assume watcher is OK."""
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue.platform") as mock_plat:
            mock_plat.system.return_value = "Linux"
            assert _check_watcher_health(str(project)) is True


# ---------------------------------------------------------------------------
# enqueue_cmd with watcher warning
# ---------------------------------------------------------------------------


class TestEnqueueWatcherWarning:
    def test_warns_when_watcher_not_loaded(self, tmp_path, capsys):
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue._check_watcher_health", return_value=False):
            rc = enqueue_cmd(
                project_dir=str(project),
                target="claude-code",
                task_id="T-1",
                item_id=None,
                priority=2,
            )
        assert rc == 0  # warn, not block
        captured = capsys.readouterr()
        assert "watcher not loaded" in captured.err.lower()

    def test_no_warning_when_watcher_loaded(self, tmp_path, capsys):
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue._check_watcher_health", return_value=True):
            rc = enqueue_cmd(
                project_dir=str(project),
                target="claude-code",
                task_id="T-1",
                item_id=None,
                priority=2,
            )
        assert rc == 0
        captured = capsys.readouterr()
        assert "watcher" not in captured.err.lower()


# ---------------------------------------------------------------------------
# enqueue_cmd with --require-watcher gate
# ---------------------------------------------------------------------------


class TestEnqueueWatcherGate:
    def test_gate_blocks_when_watcher_not_loaded(self, tmp_path):
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue._check_watcher_health", return_value=False):
            with pytest.raises(SystemExit) as exc:
                enqueue_cmd(
                    project_dir=str(project),
                    target="claude-code",
                    task_id="T-1",
                    item_id=None,
                    priority=2,
                    require_watcher=True,
                )
            assert exc.value.code == 1

    def test_gate_passes_when_watcher_loaded(self, tmp_path):
        project = _setup_project(tmp_path)
        with patch("superharness.commands.inbox_enqueue._check_watcher_health", return_value=True):
            rc = enqueue_cmd(
                project_dir=str(project),
                target="claude-code",
                task_id="T-1",
                item_id=None,
                priority=2,
                require_watcher=True,
            )
        assert rc == 0
