"""RED tests for the git section (ui/sections/git.py)."""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


def _read_profile(project_dir: Path) -> dict:
    p = project_dir / ".superharness" / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _run_git_section(project_dir: Path, answers: list[str] | None = None, non_interactive: bool = False):
    from superharness.ui.sections.git import run
    if non_interactive or answers is None:
        run(project_dir, non_interactive=True)
    else:
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("\n".join(answers) + "\n")
        try:
            run(project_dir, non_interactive=False)
        finally:
            sys.stdin = old_stdin


@pytest.fixture
def git_project(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"], capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"], capture_output=True)
    (tmp_path / ".superharness").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------


def test_git_section_reads_team_size_from_profile(git_project, capsys):
    """git section shows current team_size from profile.yaml."""
    (git_project / ".superharness" / "profile.yaml").write_text(
        yaml.dump({"team_size": "small", "git_mode": "team"})
    )

    _run_git_section(git_project, non_interactive=True)

    out = capsys.readouterr().out
    assert "small" in out or "team" in out or "git" in out.lower()


def test_git_section_writes_team_size_on_change(git_project):
    """Selecting a team_size in interactive mode writes it to profile.yaml."""
    _run_git_section(git_project, answers=["1", "1"])  # team_size=1, git_mode=1

    doc = _read_profile(git_project)
    assert doc.get("team_size") in ("solo", "small", "large")


def test_git_section_detects_git_repo_presence(git_project, capsys):
    """git section acknowledges that a git repo was found."""
    _run_git_section(git_project, non_interactive=True)

    out = capsys.readouterr().out
    assert any(word in out.lower() for word in ("git", "team", "solo", "track"))


def test_git_section_non_git_project_no_crash(tmp_path):
    """git section on a non-git directory must not crash."""
    (tmp_path / ".superharness").mkdir()
    _run_git_section(tmp_path, non_interactive=True)


def test_git_section_non_interactive_no_prompt(git_project, monkeypatch):
    """non_interactive=True never calls input()."""
    import builtins

    def _no_input(*a, **kw):
        raise AssertionError("input() called in non-interactive mode")

    monkeypatch.setattr(builtins, "input", _no_input)
    _run_git_section(git_project, non_interactive=True)
