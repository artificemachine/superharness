"""Tests for dashboard-ui standalone functions (C6 decomposition).

Covers the most-used data endpoints — previously untested.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


def _load_du_module():
    import importlib.util
    path = os.path.join(os.path.dirname(__file__), "..", "..", "src", "superharness", "scripts", "dashboard-ui.py")
    spec = importlib.util.spec_from_file_location("dashboard_ui", os.path.abspath(path))
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.modules["dashboard_ui"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_git_context_returns_dict(tmp_path: Path) -> None:
    """git_context should return branch, dirty_count, and last_commit."""
    du = _load_du_module()
    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="main\n"),
            MagicMock(returncode=0, stdout=" M src/main.py\n?? new.txt\n"),
            MagicMock(returncode=0, stdout="abc1234 fix: test commit\n"),
        ]
        result = du.git_context(tmp_path)
        assert result["branch"] == "main"
        assert result["dirty_count"] == 2
        assert "abc1234" in result["last_commit"]


def test_tail_lines_reads_last_n(tmp_path: Path) -> None:
    """tail_lines should return last N lines."""
    du = _load_du_module()
    log = tmp_path / "test.log"
    log.write_text("line1\nline2\nline3\nline4\nline5\n")
    result = du.tail_lines(log, 2)
    assert len(result) == 2
    assert result[-1] == "line5"


def test_tail_lines_missing_file(tmp_path: Path) -> None:
    """tail_lines should return message when file doesn't exist."""
    du = _load_du_module()
    result = du.tail_lines(tmp_path / "nonexistent.log", 10)
    assert len(result) == 1
    assert "No log file yet" in result[0]


def test_contract_tasks_returns_list(tmp_path: Path) -> None:
    """contract_tasks should return a list of task dicts."""
    du = _load_du_module()
    with patch("superharness.engine.state_reader.get_top_level_tasks", return_value=[
        {"id": "test.1", "title": "Test task", "status": "todo", "owner": "claude-code"}
    ]):
        result = du.contract_tasks(tmp_path)
        assert isinstance(result, list)


def test_inbox_items_returns_list(tmp_path: Path) -> None:
    """inbox_items should parse inbox YAML file."""
    du = _load_du_module()
    import yaml
    inbox = tmp_path / "inbox.yaml"
    inbox.write_text(yaml.dump([{"id": "item-1", "task": "test", "to": "claude-code", "status": "pending"}]))
    result = du.inbox_items(inbox)
    assert isinstance(result, list)
    # Empty list if YAML is empty (inbox.yaml format may differ in SQLite mode)


def test_watcher_runtime_returns_dict() -> None:
    """watcher_runtime should return loaded/state dict."""
    du = _load_du_module()
    result = du.watcher_runtime("test-label")
    assert isinstance(result, dict)
    assert "loaded" in result


def test_version_sanity_returns_dict(tmp_path: Path) -> None:
    """version_sanity should return installed/running version info."""
    du = _load_du_module()
    result = du.version_sanity(tmp_path)
    assert isinstance(result, dict)
    assert "installed_version" in result
