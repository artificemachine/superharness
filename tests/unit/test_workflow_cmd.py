"""Iteration 4: shux workflow CLI — reads/writes profile.yaml.

Tests the non-interactive (flag-based) path only. Interactive path
requires a real TTY which subprocess tests cannot provide.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tests.helpers import seed_sqlite_from_yaml, get_task_from_sqlite

import yaml

PYTHON = sys.executable


def _make_project(tmp_path: Path, profile: dict | None = None) -> Path:
    project = tmp_path / "proj"
    sh = project / ".superharness"
    sh.mkdir(parents=True)
    (sh / "contract.yaml").write_text("id: proj\ntasks:\n")
    if profile is not None:
        (sh / "profile.yaml").write_text(yaml.dump(profile))
    seed_sqlite_from_yaml(project)
    return project


def _run_workflow(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "superharness.commands.workflow_cmd",
         "--project", str(project)] + list(args),
        capture_output=True, text=True, check=False,
    )


def _read_profile(project: Path) -> dict:
    p = project / ".superharness" / "profile.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


# ---------------------------------------------------------------------------
# --show
# ---------------------------------------------------------------------------

def test_show_prints_current_settings_defaults(tmp_path: Path) -> None:
    """--show on empty profile prints defaults."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--show")
    assert r.returncode == 0, r.stderr
    out = r.stdout.lower()
    assert "ai_driven" in out
    assert "implementation" in out or "default_preset" in out
    assert "require_tdd" in out or "tdd" in out


def test_show_reflects_written_profile(tmp_path: Path) -> None:
    """--show reflects values written to profile.yaml."""
    project = _make_project(tmp_path, profile={
        "autonomy": "oversight",
        "workflow": {"default_preset": "quick", "require_tdd": False},
    })
    r = _run_workflow(project, "--show")
    assert r.returncode == 0, r.stderr
    assert "oversight" in r.stdout


def test_json_output_shape(tmp_path: Path) -> None:
    """--show --json returns correct shape with expected keys."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--show", "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert "autonomy" in data
    assert "workflow" in data
    assert "default_preset" in data["workflow"]
    assert "require_tdd" in data["workflow"]


# ---------------------------------------------------------------------------
# --autonomy flag
# ---------------------------------------------------------------------------

def test_flag_sets_autonomy_oversight(tmp_path: Path) -> None:
    """--autonomy oversight writes profile.yaml."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--autonomy", "oversight")
    assert r.returncode == 0, r.stderr
    assert _read_profile(project).get("autonomy") == "oversight"


def test_flag_sets_autonomy_hands_on(tmp_path: Path) -> None:
    """--autonomy hands_on writes profile.yaml."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--autonomy", "hands_on")
    assert r.returncode == 0, r.stderr
    assert _read_profile(project).get("autonomy") == "hands_on"


def test_flag_sets_autonomy_ai_driven(tmp_path: Path) -> None:
    """--autonomy ai_driven writes profile.yaml."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--autonomy", "ai_driven")
    assert r.returncode == 0, r.stderr
    assert _read_profile(project).get("autonomy") == "ai_driven"


def test_invalid_autonomy_rejected(tmp_path: Path) -> None:
    """--autonomy invalid_value → exit 2, error mentions valid values."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--autonomy", "invalid_value")
    assert r.returncode == 2
    err = (r.stderr + r.stdout).lower()
    assert "ai_driven" in err or "autonomy" in err


# ---------------------------------------------------------------------------
# --default-preset flag
# ---------------------------------------------------------------------------

def test_flag_sets_default_preset(tmp_path: Path) -> None:
    """--default-preset quick writes workflow.default_preset."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--default-preset", "quick")
    assert r.returncode == 0, r.stderr
    profile = _read_profile(project)
    assert profile.get("workflow", {}).get("default_preset") == "quick"


def test_invalid_preset_rejected(tmp_path: Path) -> None:
    """--default-preset bogus → exit 2."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--default-preset", "bogus")
    assert r.returncode == 2


# ---------------------------------------------------------------------------
# --require-tdd / --no-require-tdd flags
# ---------------------------------------------------------------------------

def test_flag_sets_require_tdd_true(tmp_path: Path) -> None:
    """--require-tdd writes workflow.require_tdd=True."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--require-tdd")
    assert r.returncode == 0, r.stderr
    assert _read_profile(project).get("workflow", {}).get("require_tdd") is True


def test_flag_sets_require_tdd_false(tmp_path: Path) -> None:
    """--no-require-tdd writes workflow.require_tdd=False."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project, "--no-require-tdd")
    assert r.returncode == 0, r.stderr
    assert _read_profile(project).get("workflow", {}).get("require_tdd") is False


# ---------------------------------------------------------------------------
# Preservation of existing fields
# ---------------------------------------------------------------------------

def test_preserves_existing_fields(tmp_path: Path) -> None:
    """After --autonomy, other profile fields like primary_agent are preserved."""
    project = _make_project(tmp_path, profile={
        "primary_agent": "claude-code",
        "project_name": "myproj",
        "autonomy": "ai_driven",
    })
    r = _run_workflow(project, "--autonomy", "hands_on")
    assert r.returncode == 0, r.stderr
    profile = _read_profile(project)
    assert profile.get("primary_agent") == "claude-code"
    assert profile.get("project_name") == "myproj"
    assert profile.get("autonomy") == "hands_on"


# ---------------------------------------------------------------------------
# Non-interactive without flags
# ---------------------------------------------------------------------------

def test_non_tty_no_flags_prints_current_settings(tmp_path: Path) -> None:
    """Non-TTY without any flags → shows current settings and exits 0."""
    project = _make_project(tmp_path, profile=None)
    r = _run_workflow(project)
    assert r.returncode == 0, r.stderr
    assert len(r.stdout) > 0
