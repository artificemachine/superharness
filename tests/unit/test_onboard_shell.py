"""Tests for onboard section registry + shell — RED phase for I2."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tests.helpers import REPO_ROOT


def _run_onboard(cwd, args: list[str], stdin: str = "", env: dict | None = None):
    import os
    merged = os.environ.copy()
    merged["PYTHONPATH"] = str(REPO_ROOT / "src")
    if env:
        for k, v in env.items():
            merged[k] = v if v is not None else merged.pop(k, None) or ""
    cmd = [sys.executable, "-m", "superharness.commands.onboard"] + args
    return subprocess.run(
        cmd, cwd=str(cwd), text=True, capture_output=True,
        input=stdin, env=merged, check=False,
    )


# ---------------------------------------------------------------------------
# Section registry
# ---------------------------------------------------------------------------

def test_onboard_sections_registry_exists():
    from superharness.commands.onboard import ONBOARD_SECTIONS
    keys = [k for k, _, _ in ONBOARD_SECTIONS]
    assert "project" in keys
    assert "agent" in keys
    assert "git" in keys
    assert "hooks" in keys
    assert "watcher" in keys
    assert "gateway" in keys
    assert "task" in keys


def test_onboard_section_only_mode_runs_single_section(tmp_path):
    (tmp_path / ".superharness").mkdir()
    result = _run_onboard(tmp_path, ["--section", "agent", "--non-interactive"])
    assert result.returncode == 0
    assert "agent" in result.stdout.lower() or "Agent" in result.stdout


def test_onboard_unknown_section_prints_error_and_exits_nonzero(tmp_path):
    result = _run_onboard(tmp_path, ["--section", "doesnotexist", "--non-interactive"])
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "unknown" in combined.lower() or "invalid" in combined.lower()


def test_onboard_section_only_shows_valid_sections_in_error(tmp_path):
    result = _run_onboard(tmp_path, ["--section", "doesnotexist", "--non-interactive"])
    combined = result.stdout + result.stderr
    assert "agent" in combined or "project" in combined


# ---------------------------------------------------------------------------
# Non-interactive / headless guidance
# ---------------------------------------------------------------------------

def test_onboard_non_interactive_prints_guidance(tmp_path):
    result = _run_onboard(tmp_path, ["--non-interactive"])
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    assert "non-interactive" in combined.lower()
    assert "shux onboard" in combined or "--non-interactive" in combined


def test_onboard_non_interactive_does_not_hang(tmp_path):
    """Must exit quickly without waiting for input."""
    import time
    start = time.monotonic()
    result = _run_onboard(tmp_path, ["--non-interactive"])
    elapsed = time.monotonic() - start
    assert result.returncode == 0
    assert elapsed < 5.0, f"onboard --non-interactive took {elapsed:.1f}s (too slow)"


# ---------------------------------------------------------------------------
# Returning-user detection
# ---------------------------------------------------------------------------

def test_onboard_returning_user_gets_menu_hint(tmp_path):
    """With existing .superharness/state.sqlite3, output mentions quick/full options."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    # Create a minimal state.sqlite3 to signal existing install
    import sqlite3
    conn = sqlite3.connect(str(sh / "state.sqlite3"))
    conn.execute("CREATE TABLE _marker (id INTEGER PRIMARY KEY)")
    conn.close()

    result = _run_onboard(tmp_path, ["--non-interactive"])
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    # Should mention quick or reconfigure options
    assert "quick" in combined.lower() or "reconfigure" in combined.lower() or "full" in combined.lower()


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def test_onboard_creates_profile_yaml_with_config_version(tmp_path):
    _run_onboard(tmp_path, ["--non-interactive"])
    profile = tmp_path / ".superharness" / "profile.yaml"
    assert profile.exists(), "profile.yaml must be created on first onboard"
    import yaml
    doc = yaml.safe_load(profile.read_text()) or {}
    assert "_config_version" in doc, "profile.yaml must contain _config_version"
    assert isinstance(doc["_config_version"], int)
