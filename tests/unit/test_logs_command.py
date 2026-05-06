"""TDD tests for shux logs command."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")


def _env(tmp_path: Path) -> dict[str, str]:
    e = os.environ.copy()
    e["PYTHONPATH"] = SRC
    e["SUPERHARNESS_LOG_FILE"] = str(tmp_path / "main.log")
    e["SUPERHARNESS_AUDIT_LOG_FILE"] = str(tmp_path / "audit.log")
    return e


def _seed(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def test_logs_path_prints_main_log_path(tmp_path):
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs", "--path"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode == 0
    assert str(tmp_path / "main.log") in res.stdout


def test_logs_path_audit_prints_audit_path(tmp_path):
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs", "--path", "--audit"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode == 0
    assert str(tmp_path / "audit.log") in res.stdout


def test_logs_prints_trailing_lines(tmp_path):
    _seed(tmp_path / "main.log", [
        "2026-05-06T01:00:00Z INFO superharness.x:fn:1 first line",
        "2026-05-06T01:00:01Z INFO superharness.x:fn:2 second line",
        "2026-05-06T01:00:02Z ERROR superharness.x:fn:3 third line",
    ])
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs", "-n", "2"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode == 0
    assert "first line" not in res.stdout
    assert "second line" in res.stdout
    assert "third line" in res.stdout


def test_logs_filters_by_level(tmp_path):
    _seed(tmp_path / "main.log", [
        "2026-05-06T01:00:00Z DEBUG superharness.x:fn:1 debug-line",
        "2026-05-06T01:00:01Z INFO superharness.x:fn:2 info-line",
        "2026-05-06T01:00:02Z ERROR superharness.x:fn:3 error-line",
    ])
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs", "--level", "ERROR"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode == 0
    assert "debug-line" not in res.stdout
    assert "info-line" not in res.stdout
    assert "error-line" in res.stdout


def test_logs_audit_reads_audit_file(tmp_path):
    _seed(tmp_path / "audit.log", [
        "2026-05-06T01:00:00Z INFO superharness.audit:fn:1 launchctl load",
    ])
    _seed(tmp_path / "main.log", ["2026-05-06T01:00:00Z INFO superharness.x:fn:1 main-only"])
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs", "--audit"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode == 0
    assert "launchctl load" in res.stdout
    assert "main-only" not in res.stdout


def test_logs_missing_file_returns_nonzero(tmp_path):
    # Don't seed any log file
    res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.logs"],
        capture_output=True, text=True, env=_env(tmp_path), check=False, timeout=10,
    )
    assert res.returncode != 0
    assert "No log file" in res.stderr
