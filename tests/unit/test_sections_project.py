"""RED tests for the project section (ui/sections/project.py)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml


def _read_profile(project_dir: Path) -> dict:
    p = project_dir / ".superharness" / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _run_project_section(project_dir: Path, answers: list[str] | None = None, non_interactive: bool = False):
    """Call the project section, injecting stdin answers or running headless."""
    from superharness.ui.sections.project import run
    if non_interactive or answers is None:
        run(project_dir, non_interactive=True)
    else:
        import io
        import sys
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("\n".join(answers) + "\n")
        try:
            run(project_dir, non_interactive=False)
        finally:
            sys.stdin = old_stdin


# ---------------------------------------------------------------------------


def test_project_section_reads_project_name_from_profile(tmp_path, capsys):
    """project section shows the current project_name stored in profile.yaml."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "profile.yaml").write_text(yaml.dump({"project_name": "my-cool-project"}))

    _run_project_section(tmp_path, non_interactive=True)

    out = capsys.readouterr().out
    assert "my-cool-project" in out


def test_project_section_writes_new_name_to_profile(tmp_path):
    """When user provides a new name the section writes it to profile.yaml."""
    (tmp_path / ".superharness").mkdir()

    _run_project_section(tmp_path, answers=["new-project-name"])

    doc = _read_profile(tmp_path)
    assert doc.get("project_name") == "new-project-name"


def test_project_section_keeps_current_value_on_empty_input(tmp_path):
    """Empty input keeps the current project_name unchanged."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "profile.yaml").write_text(yaml.dump({"project_name": "keep-me"}))

    _run_project_section(tmp_path, answers=[""])

    doc = _read_profile(tmp_path)
    assert doc.get("project_name") == "keep-me"


def test_project_section_creates_profile_if_absent(tmp_path):
    """project section creates profile.yaml when it doesn't exist."""
    (tmp_path / ".superharness").mkdir()

    _run_project_section(tmp_path, non_interactive=True)

    assert (tmp_path / ".superharness" / "profile.yaml").exists()
    doc = _read_profile(tmp_path)
    # At minimum project_name should be set (defaults to dir name)
    assert "project_name" in doc


def test_project_section_non_interactive_does_not_prompt(tmp_path, monkeypatch):
    """non_interactive=True never calls input()."""
    import builtins
    (tmp_path / ".superharness").mkdir()

    def _no_input(*a, **kw):
        raise AssertionError("input() called in non-interactive mode")

    monkeypatch.setattr(builtins, "input", _no_input)
    _run_project_section(tmp_path, non_interactive=True)
