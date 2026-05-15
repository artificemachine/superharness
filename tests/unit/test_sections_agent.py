"""RED tests for the agent section (ui/sections/agent.py)."""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
import yaml


def _read_profile(project_dir: Path) -> dict:
    p = project_dir / ".superharness" / "profile.yaml"
    return yaml.safe_load(p.read_text()) if p.exists() else {}


def _run_agent_section(project_dir: Path, answers: list[str] | None = None, non_interactive: bool = False):
    from superharness.ui.sections.agent import run
    if non_interactive or answers is None:
        run(project_dir, non_interactive=True)
    else:
        old_stdin = sys.stdin
        sys.stdin = io.StringIO("\n".join(answers) + "\n")
        try:
            run(project_dir, non_interactive=False)
        finally:
            sys.stdin = old_stdin


# ---------------------------------------------------------------------------


def test_agent_section_reads_primary_agent_and_autonomy(tmp_path, capsys):
    """Agent section shows current autonomy and primary_agent from profile."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "profile.yaml").write_text(yaml.dump({
        "autonomy": "ai_driven",
        "primary_agent": "codex-cli",
    }))

    _run_agent_section(tmp_path, non_interactive=True)

    out = capsys.readouterr().out
    assert "ai_driven" in out or "codex-cli" in out


def test_agent_section_writes_autonomy_on_valid_choice(tmp_path):
    """Choosing a valid autonomy option writes it to profile.yaml."""
    (tmp_path / ".superharness").mkdir()

    _run_agent_section(tmp_path, answers=["1", ""])  # autonomy choice=1 (ai_driven), agent=keep

    doc = _read_profile(tmp_path)
    assert doc.get("autonomy") == "ai_driven"


def test_agent_section_writes_primary_agent(tmp_path):
    """Entering a primary agent name writes it to profile.yaml."""
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "profile.yaml").write_text(yaml.dump({"primary_agent": ""}))

    _run_agent_section(tmp_path, answers=["1", "claude-code"])  # pick autonomy 1, then set agent

    doc = _read_profile(tmp_path)
    assert doc.get("primary_agent") == "claude-code"


def test_agent_section_non_interactive_no_prompt(tmp_path, monkeypatch):
    """non_interactive=True never calls input()."""
    import builtins
    (tmp_path / ".superharness").mkdir()

    def _no_input(*a, **kw):
        raise AssertionError("input() called in non-interactive mode")

    monkeypatch.setattr(builtins, "input", _no_input)
    _run_agent_section(tmp_path, non_interactive=True)


def test_agent_section_creates_profile_if_absent(tmp_path):
    """agent section creates profile.yaml when it doesn't exist."""
    (tmp_path / ".superharness").mkdir()
    _run_agent_section(tmp_path, non_interactive=True)
    assert (tmp_path / ".superharness" / "profile.yaml").exists()
