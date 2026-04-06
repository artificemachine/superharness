"""Tests for shux onboard — interactive setup wizard (TDD: written before implementation)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def project(tmp_path):
    """Minimal git repo without .superharness/."""
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], capture_output=True)
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"], capture_output=True)
    return tmp_path


@pytest.fixture
def initialized_project(project):
    """Project with .superharness/ already set up."""
    sh = project / ".superharness"
    sh.mkdir()
    (sh / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (sh / "ledger.md").write_text("# Ledger\n")
    return project


# ---------------------------------------------------------------------------
# Step state + resumability
# ---------------------------------------------------------------------------

def test_onboard_creates_state_file(runner, project):
    """onboarding.yaml is written after a run."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    state_file = project / ".superharness" / "onboarding.yaml"
    assert state_file.exists(), "onboarding.yaml not created"


def test_onboard_skips_init_if_exists(runner, initialized_project):
    """If .superharness/ already exists, the init step is skipped."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(initialized_project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    assert "skip" in result.output.lower() or "already" in result.output.lower()


def test_onboard_resumes_from_last_step(runner, project):
    """Partial onboarding.yaml → wizard picks up from where it stopped."""
    from superharness.commands.onboard import cmd_onboard
    sh = project / ".superharness"
    sh.mkdir()
    (sh / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (sh / "ledger.md").write_text("# Ledger\n")
    # Simulate having completed only detect + init
    state = {
        "version": 1,
        "steps": {"detect": "completed", "init": "completed",
                  "git_track": "pending", "doctor": "pending",
                  "task": "pending", "delegate": "pending", "summary": "pending"},
    }
    (sh / "onboarding.yaml").write_text(yaml.dump(state))

    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    # Should not re-run detect/init
    assert result.output.count("Step 1") == 0 or "skip" in result.output.lower()


def test_onboard_idempotent(runner, project):
    """Running onboard twice doesn't duplicate state or crash."""
    from superharness.commands.onboard import cmd_onboard
    args = ["--project", str(project), "--non-interactive"]
    r1 = runner.invoke(cmd_onboard, args)
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(cmd_onboard, args)
    assert r2.exit_code == 0, r2.output


# ---------------------------------------------------------------------------
# Step 1 — detect
# ---------------------------------------------------------------------------

def test_onboard_step_detect_shows_stack(runner, project):
    """Output contains the detected project stack."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    # detect step runs and prints something about the project
    assert any(word in result.output.lower() for word in ("detect", "project", "git", "stack", "found"))


# ---------------------------------------------------------------------------
# Step 3 — git tracking
# ---------------------------------------------------------------------------

def test_onboard_git_track_team_keeps_commit(runner, project):
    """team mode: .superharness/ must NOT appear in root .gitignore."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive", "--git-mode", "team",
    ])
    assert result.exit_code == 0, result.output
    gitignore = project / ".gitignore"
    if gitignore.exists():
        assert ".superharness" not in gitignore.read_text(), \
            ".superharness/ must not be gitignored in team mode"


def test_onboard_git_track_solo_adds_gitignore(runner, project):
    """solo mode: .superharness/ appended to root .gitignore."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive", "--git-mode", "solo",
    ])
    assert result.exit_code == 0, result.output
    gitignore = project / ".gitignore"
    assert gitignore.exists(), ".gitignore not created"
    assert ".superharness" in gitignore.read_text()


def test_onboard_git_track_idempotent(runner, project):
    """Running twice with solo mode doesn't duplicate .gitignore entry."""
    from superharness.commands.onboard import cmd_onboard
    args = ["--project", str(project), "--non-interactive", "--git-mode", "solo"]
    runner.invoke(cmd_onboard, args)
    runner.invoke(cmd_onboard, args)
    gitignore = project / ".gitignore"
    content = gitignore.read_text()
    assert content.count(".superharness") == 1, "duplicate .superharness entry in .gitignore"


def test_onboard_git_track_inner_gitignore(runner, project):
    """Inner .superharness/.gitignore always created with runtime exclusions."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    inner = project / ".superharness" / ".gitignore"
    assert inner.exists(), ".superharness/.gitignore not created"
    content = inner.read_text()
    assert "watcher-env.yaml" in content
    assert "launcher-logs" in content


def test_onboard_fails_gracefully_without_git(runner, tmp_path):
    """Non-git project: step 3 is skipped, not crashed."""
    from superharness.commands.onboard import cmd_onboard
    (tmp_path / "somefile.txt").write_text("hi\n")
    result = runner.invoke(cmd_onboard, [
        "--project", str(tmp_path), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    assert "skip" in result.output.lower() or "no git" in result.output.lower()


# ---------------------------------------------------------------------------
# Step 4 — doctor
# ---------------------------------------------------------------------------

def test_onboard_doctor_failure_non_blocking(runner, project):
    """Doctor warnings don't prevent reaching the summary step."""
    from superharness.commands.onboard import cmd_onboard
    # Run without any special agents installed — doctor will warn but not block
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    assert "summary" in result.output.lower() or "set up" in result.output.lower()


# ---------------------------------------------------------------------------
# Step 5 — first task
# ---------------------------------------------------------------------------

def test_onboard_step_task_creates_entry(runner, project):
    """--task-title creates a task entry in contract.yaml."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
        "--task-title", "Add login page",
    ])
    assert result.exit_code == 0, result.output
    contract = project / ".superharness" / "contract.yaml"
    assert contract.exists()
    doc = yaml.safe_load(contract.read_text())
    titles = [t.get("title", "") for t in doc.get("tasks", [])]
    assert any("login" in t.lower() for t in titles), f"task not found in contract: {titles}"


# ---------------------------------------------------------------------------
# Step 6 — delegate
# ---------------------------------------------------------------------------

def test_onboard_step_delegate_enqueues(runner, project):
    """--enqueue adds the task to inbox.yaml."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
        "--task-title", "Fix the bug",
        "--enqueue",
    ])
    assert result.exit_code == 0, result.output
    inbox = project / ".superharness" / "inbox.yaml"
    assert inbox.exists(), "inbox.yaml not created after --enqueue"
    items = yaml.safe_load(inbox.read_text()) or []
    assert len(items) > 0, "no items in inbox after --enqueue"


# ---------------------------------------------------------------------------
# Step 7 — summary
# ---------------------------------------------------------------------------

def test_onboard_summary_shows_next_steps(runner, project):
    """Summary output contains 'shux contract' as a next step."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    assert "shux contract" in result.output


# ---------------------------------------------------------------------------
# Non-interactive + missing agent CLI
# ---------------------------------------------------------------------------

def test_onboard_non_interactive_no_prompts(runner, project, monkeypatch):
    """--non-interactive never calls input() or click.prompt()."""
    import builtins
    original_input = builtins.input

    def _no_input(*a, **kw):
        raise AssertionError("input() called in non-interactive mode")

    monkeypatch.setattr(builtins, "input", _no_input)
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output


def test_onboard_works_without_agent_cli(runner, project, monkeypatch):
    """No agent CLI installed → step 6 uses print-only mode, doesn't crash."""
    # Patch PATH so no agent CLIs are found
    monkeypatch.setenv("PATH", "/nonexistent")
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
        "--task-title", "test task",
        "--enqueue",
    ])
    # Should complete without crashing (may skip real enqueue, but no exception)
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# AGENTS.md creation
# ---------------------------------------------------------------------------

def test_onboard_creates_agents_md(runner, project):
    """Step 2 (init) writes AGENTS.md if it doesn't exist."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    agents_md = project / "AGENTS.md"
    assert agents_md.exists(), "AGENTS.md not created by onboard"
    content = agents_md.read_text()
    assert "shux contract" in content, "AGENTS.md should mention shux contract"


def test_onboard_does_not_overwrite_agents_md(runner, project):
    """If AGENTS.md already exists, onboard must NOT overwrite it."""
    existing = "# My custom AGENTS.md\nDo not overwrite me.\n"
    (project / "AGENTS.md").write_text(existing)
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    assert (project / "AGENTS.md").read_text() == existing, "AGENTS.md was overwritten"


# ---------------------------------------------------------------------------
# Step hints (→ context lines)
# ---------------------------------------------------------------------------

def test_onboard_steps_have_context_hints(runner, project):
    """Each step prints at least one → hint line explaining what was done."""
    from superharness.commands.onboard import cmd_onboard
    result = runner.invoke(cmd_onboard, [
        "--project", str(project), "--non-interactive",
    ])
    assert result.exit_code == 0, result.output
    assert "→" in result.output, "No → hint lines found in onboard output"
    # At least 3 distinct hint lines
    hint_lines = [l for l in result.output.splitlines() if "→" in l]
    assert len(hint_lines) >= 3, f"Expected ≥3 hint lines, got {len(hint_lines)}"


# ---------------------------------------------------------------------------
# Cold-start hint in shux --help
# ---------------------------------------------------------------------------

def test_help_cold_start_suggests_onboard(tmp_path, runner):
    """shux --help in a dir without .superharness/ mentions shux onboard."""
    from superharness.cli import main
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "onboard" in result.output.lower(), \
        "shux --help should mention 'onboard' for cold-start projects"
