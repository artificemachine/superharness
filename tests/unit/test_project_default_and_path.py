"""
Tests for:
1. shux hygiene defaults --project to cwd when omitted
2. delegate._expand_path augments PATH with common user-local dirs
"""
from __future__ import annotations

import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from tests.helpers import REPO_ROOT


# ── helpers ────────────────────────────────────────────────────────────────

def _run_hygiene(cwd, args: list[str] | None = None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    cmd = [sys.executable, "-m", "superharness.engine.validate"] + (args or [])
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)


def _make_valid_project(path):
    """Create a minimal valid superharness project."""
    harness = path / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text(
        "id: test\nstatus: active\ntasks: []\ndecisions: []\nfailures: []\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n")
    (harness / "handoffs").mkdir()
    (harness / "decisions.yaml").write_text("decisions: []\n")
    (harness / "failures.yaml").write_text("failures: []\n")


# ── hygiene: --project defaults to cwd ────────────────────────────────────

def test_hygiene_uses_cwd_when_project_not_given(tmp_path):
    """shux hygiene with no --project should run against cwd, not error."""
    _make_valid_project(tmp_path)
    result = _run_hygiene(tmp_path)   # no --project arg
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert "passed" in result.stdout.lower()


def test_hygiene_explicit_project_still_works(tmp_path):
    """Explicit --project flag must still work."""
    _make_valid_project(tmp_path)
    result = _run_hygiene(tmp_path, args=["--project", str(tmp_path)])
    assert result.returncode == 0
    assert "passed" in result.stdout.lower()


def test_hygiene_no_project_no_superharness_dir_fails_gracefully(tmp_path):
    """Running hygiene in a dir with no .superharness/ should fail, not crash."""
    result = _run_hygiene(tmp_path)
    assert result.returncode != 0
    # Should not be a Python traceback
    assert "Traceback" not in result.stderr


# ── delegate: PATH expansion ───────────────────────────────────────────────

def test_expand_path_adds_local_bin_when_missing():
    from superharness.commands.delegate import _expand_path
    original_path = os.environ.get("PATH", "")
    try:
        # Strip ~/.local/bin from PATH to simulate launchd environment
        local_bin = os.path.expanduser("~/.local/bin")
        stripped = os.pathsep.join(
            p for p in original_path.split(os.pathsep) if p != local_bin
        )
        os.environ["PATH"] = stripped
        _expand_path()
        new_path = os.environ.get("PATH", "")
        if os.path.isdir(local_bin):
            assert local_bin in new_path, f"~/.local/bin not added; PATH={new_path}"
    finally:
        os.environ["PATH"] = original_path


def test_expand_path_does_not_duplicate_existing_entries():
    from superharness.commands.delegate import _expand_path
    original_path = os.environ.get("PATH", "")
    try:
        local_bin = os.path.expanduser("~/.local/bin")
        # Start with a clean PATH that contains local_bin exactly once
        os.environ["PATH"] = "/usr/bin:/bin" + os.pathsep + local_bin
        _expand_path()
        entries = [e for e in os.environ["PATH"].split(os.pathsep) if e]
        assert entries.count(local_bin) == 1, "Duplicate PATH entry added"
    finally:
        os.environ["PATH"] = original_path


def test_expand_path_only_adds_existing_dirs(tmp_path):
    """Non-existent dirs must not be added to PATH."""
    from superharness.commands.delegate import _expand_path
    original_path = os.environ.get("PATH", "")
    try:
        os.environ["PATH"] = "/usr/bin:/bin"
        _expand_path()
        new_entries = os.environ["PATH"].split(os.pathsep)
        for entry in new_entries:
            assert os.path.isdir(entry) or entry == "", f"Non-existent dir in PATH: {entry}"
    finally:
        os.environ["PATH"] = original_path


def test_cmd_exists_finds_python_after_path_expansion():
    """After expansion, well-known binaries on the system should be findable."""
    from superharness.commands.delegate import _cmd_exists
    # python3 is always available in our test env
    assert _cmd_exists("python3") or _cmd_exists("python")
