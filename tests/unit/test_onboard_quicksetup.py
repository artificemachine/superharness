"""RED tests for I4: quick-setup, config version bumping, summary printer."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path):
    """Minimal project dir without .superharness/ (no git needed for most tests)."""
    (tmp_path / ".superharness").mkdir()
    return tmp_path


@pytest.fixture
def git_project(tmp_path):
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True)
    (tmp_path / ".superharness").mkdir()
    return tmp_path


def _seed_state(project: Path, steps: dict, config_version: int | None = None):
    state: dict = {"version": 1, "steps": steps}
    if config_version is not None:
        state["config_version"] = config_version
    (project / ".superharness" / "onboarding.yaml").write_text(yaml.dump(state))


def _read_state(project: Path) -> dict:
    f = project / ".superharness" / "onboarding.yaml"
    return yaml.safe_load(f.read_text()) if f.exists() else {}


def _all_completed(project: Path) -> dict:
    from superharness.commands.onboard import _STEPS, ONBOARD_CONFIG_VERSION
    return {s: "completed" for s in _STEPS}


# ---------------------------------------------------------------------------
# Quick-setup: skips completed steps silently
# ---------------------------------------------------------------------------

def test_quick_setup_skips_completed_steps(runner, project, tmp_path, monkeypatch):
    """After a full run, --quick produces no detect/init output (already done)."""
    from superharness.commands.onboard import cmd_onboard, ONBOARD_CONFIG_VERSION

    fake_claude_md = tmp_path / "global_claude.md"
    fake_claude_md.write_text("# superharness\n")
    monkeypatch.setenv("SUPERHARNESS_GLOBAL_CLAUDE_MD", str(fake_claude_md))

    # First full run
    r1 = runner.invoke(cmd_onboard, ["--project", str(project), "--non-interactive"])
    assert r1.exit_code == 0, r1.output

    # Second run with --quick
    r2 = runner.invoke(cmd_onboard, ["--project", str(project), "--quick", "--non-interactive"])
    assert r2.exit_code == 0, r2.output

    # Step banners ([detect] / [skip] Step 1 (detect)) must NOT appear — quick skips silently.
    # Note: "detect" still appears in the summary status table ("✓ detect"), which is expected.
    assert "[detect]" not in r2.output
    assert "step 1 (detect)" not in r2.output.lower()
    assert "[init]" not in r2.output
    assert "step 2 (init)" not in r2.output.lower()
    # Summary must still be shown
    assert "shux contract" in r2.output or "✓" in r2.output or "set up" in r2.output.lower()


def test_quick_setup_runs_pending_steps(runner, project, monkeypatch):
    """--quick runs steps still marked pending while silently skipping completed ones."""
    from superharness.commands.onboard import cmd_onboard, ONBOARD_CONFIG_VERSION

    fake_claude_md = project.parent / "global_claude.md"
    fake_claude_md.write_text("# superharness\n")
    monkeypatch.setenv("SUPERHARNESS_GLOBAL_CLAUDE_MD", str(fake_claude_md))

    # Seed: detect + init + global_claude completed, git_track pending
    _seed_state(project, {
        "detect": "completed",
        "init": "completed",
        "global_claude": "completed",
        "git_track": "pending",
        "doctor": "pending",
        "task": "pending",
        "delegate": "pending",
        "summary": "pending",
    }, config_version=ONBOARD_CONFIG_VERSION)

    result = runner.invoke(cmd_onboard, ["--project", str(project), "--quick", "--non-interactive"])
    assert result.exit_code == 0, result.output

    # git_track step must have run (output contains "git_track" or "Step 3")
    out_lower = result.output.lower()
    assert "git_track" in out_lower or "git" in out_lower or "track" in out_lower
    # detect/init must NOT appear (they were completed and quick skipped them silently)
    assert "[detect]" not in result.output
    assert "step 1 (detect)" not in result.output.lower()
    assert "[init]" not in result.output
    assert "step 2 (init)" not in result.output.lower()


# ---------------------------------------------------------------------------
# Config version bumping
# ---------------------------------------------------------------------------

def test_config_version_bump_resets_new_steps(runner, project, monkeypatch):
    """Old onboarding.yaml (config_version=1) causes v2-new steps to re-run."""
    from superharness.commands.onboard import cmd_onboard, ONBOARD_CONFIG_VERSION, _STEPS_BY_VERSION

    # Use temp file to avoid touching real ~/.claude/CLAUDE.md
    fake_claude_md = project.parent / "fake_claude.md"
    fake_claude_md.write_text("# no superharness yet\n")
    monkeypatch.setenv("SUPERHARNESS_GLOBAL_CLAUDE_MD", str(fake_claude_md))

    # Seed: config_version=1, all steps completed (simulates pre-v2 onboarding.yaml)
    _seed_state(project, _all_completed(project), config_version=1)

    # ONBOARD_CONFIG_VERSION must be >= 2 for this test to be meaningful
    assert ONBOARD_CONFIG_VERSION >= 2

    result = runner.invoke(cmd_onboard, ["--project", str(project), "--non-interactive"])
    assert result.exit_code == 0, result.output

    # global_claude (introduced in v2) must have run — its output must appear
    assert "global_claude" in result.output.lower() or "global" in result.output.lower()


def test_config_version_updated_after_run(runner, project, monkeypatch):
    """After a full onboard run, onboarding.yaml stores config_version == ONBOARD_CONFIG_VERSION."""
    from superharness.commands.onboard import cmd_onboard, ONBOARD_CONFIG_VERSION

    fake_claude_md = project.parent / "fake_claude2.md"
    fake_claude_md.write_text("# no superharness yet\n")
    monkeypatch.setenv("SUPERHARNESS_GLOBAL_CLAUDE_MD", str(fake_claude_md))

    result = runner.invoke(cmd_onboard, ["--project", str(project), "--non-interactive"])
    assert result.exit_code == 0, result.output

    state = _read_state(project)
    assert state.get("config_version") == ONBOARD_CONFIG_VERSION


# ---------------------------------------------------------------------------
# Summary printer shows per-step status
# ---------------------------------------------------------------------------

def test_summary_shows_per_step_status(runner, project, monkeypatch):
    """Full non-interactive run: summary output contains ✓ for completed steps + shux contract."""
    from superharness.commands.onboard import cmd_onboard

    fake_claude_md = project.parent / "fake_claude3.md"
    fake_claude_md.write_text("# no superharness yet\n")
    monkeypatch.setenv("SUPERHARNESS_GLOBAL_CLAUDE_MD", str(fake_claude_md))

    result = runner.invoke(cmd_onboard, ["--project", str(project), "--non-interactive"])
    assert result.exit_code == 0, result.output

    # At least 3 "✓" symbols (or "completed") must appear
    checkmarks = result.output.count("✓")
    completeds = result.output.lower().count("completed")
    assert checkmarks >= 3 or completeds >= 3, (
        f"Expected >= 3 completed markers in output, got checkmarks={checkmarks}, completeds={completeds}\n"
        f"Output:\n{result.output}"
    )
    assert "shux contract" in result.output


def test_summary_shows_skipped_steps(runner, project, monkeypatch):
    """Summary shows completed status for seeded-completed steps and newly-run steps."""
    from superharness.commands.onboard import cmd_onboard, ONBOARD_CONFIG_VERSION

    fake_claude_md = project.parent / "fake_claude4.md"
    fake_claude_md.write_text("# no superharness yet\n")
    monkeypatch.setenv("SUPERHARNESS_GLOBAL_CLAUDE_MD", str(fake_claude_md))

    # Seed: git_track completed, doctor pending; non-git project
    _seed_state(project, {
        "detect": "completed",
        "init": "completed",
        "global_claude": "completed",
        "git_track": "completed",
        "doctor": "pending",
        "task": "pending",
        "delegate": "pending",
        "summary": "pending",
    }, config_version=ONBOARD_CONFIG_VERSION)

    result = runner.invoke(cmd_onboard, ["--project", str(project), "--non-interactive"])
    assert result.exit_code == 0, result.output

    # Summary must mention git_track and doctor with some status indicator
    out = result.output
    assert "git_track" in out or "git" in out.lower()
    assert "doctor" in out
    # At least some "✓" symbols must appear (for the completed steps)
    assert "✓" in out or "completed" in out.lower()
