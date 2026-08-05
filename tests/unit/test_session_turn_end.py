"""Tests for adapters/claude-code/hooks/session-turn-end.sh.

Closes the `session-turn-end.sh` entry in `KNOWN_UNTESTED` in
tests/contract/test_hook_test_coverage.py.

session-turn-end.sh is the turn-safe Stop hook: it fires on every
assistant turn (via Claude Code's Stop event) and ONLY writes
session-progress.md + a ledger line + surfaces pending discussion
prompts. It deliberately does NOT stop tasks, write handoffs, pause
inbox, or pkill MCP servers — those live in session-exit.sh because
they must fire on true session exit only (every turn would break the
lifecycle).

These tests pin that turn-safe contract so a future edit cannot
silently widen the hook into a per-turn destructive handler.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tests.helpers import run_bash


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "ledger.md").write_text("# Ledger\n\n")
    return project


def test_turn_end_writes_snapshot(repo_root: Path, tmp_path: Path) -> None:
    """session-progress.md must be written and contain the canonical
    section headers used by session-start.sh to restore context."""
    project = _setup_project(tmp_path)
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    result = run_bash(script, cwd=project)
    assert result.returncode == 0, result.stderr
    progress = project / ".superharness" / "session-progress.md"
    assert progress.exists(), "session-turn-end.sh must write session-progress.md"
    content = progress.read_text()
    assert "# Session Progress" in content
    assert "## Task Context" in content
    assert "## Branch" in content
    assert "## Uncommitted Changes" in content
    assert "## Recent Commits" in content
    # Generator marker — distinguishes from session-stop.sh's snapshot
    assert "session-turn-end hook" in content


def test_turn_end_appends_ledger_line(repo_root: Path, tmp_path: Path) -> None:
    """A single ledger entry marking the snapshot write must be appended."""
    project = _setup_project(tmp_path)
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    result = run_bash(script, cwd=project)
    assert result.returncode == 0, result.stderr
    ledger = (project / ".superharness" / "ledger.md").read_text()
    assert "session-turn-end" in ledger
    assert "session-progress.md" in ledger


def test_turn_end_overwrites_not_appends_snapshot(
    repo_root: Path, tmp_path: Path
) -> None:
    """Snapshot must be overwritten on each turn — appending would let it
    grow unbounded across a long session (Stop fires every turn)."""
    project = _setup_project(tmp_path)
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    run_bash(script, cwd=project)
    run_bash(script, cwd=project)
    content = (project / ".superharness" / "session-progress.md").read_text()
    assert content.count("# Session Progress") == 1, (
        "snapshot must be overwritten, not appended"
    )
    assert content.count("Last updated:") == 1


def test_turn_end_surfaces_pending_discussion_prompt(
    repo_root: Path, tmp_path: Path
) -> None:
    """When a round prompt file exists in
    .superharness/discussions/<id>/round-N-claude-code.prompt.md, the
    hook must surface it on stdout so the agent picks it up next turn."""
    project = _setup_project(tmp_path)
    disc_dir = (
        project
        / ".superharness"
        / "discussions"
        / "disc-42"
        / "round-1-claude-code.prompt.md"
    )
    disc_dir.parent.mkdir(parents=True)
    disc_dir.write_text("# Round 1 prompt\nWhat's the verdict?\n")

    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    result = run_bash(script, cwd=project)
    assert result.returncode == 0, result.stderr
    assert "PENDING DISCUSSION TASK" in result.stdout
    assert "disc-42" in result.stdout
    assert "shux discuss submit" in result.stdout, "must surface the submit command"


def test_turn_end_no_discussion_dir_is_noop_for_prompts(
    repo_root: Path, tmp_path: Path
) -> None:
    """No discussions/ dir → no PENDING DISCUSSION output, but snapshot still written."""
    project = _setup_project(tmp_path)
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    result = run_bash(script, cwd=project)
    assert result.returncode == 0, result.stderr
    assert "PENDING DISCUSSION" not in result.stdout
    assert (project / ".superharness" / "session-progress.md").exists()


def test_turn_end_noop_without_superharness_dir(
    repo_root: Path, tmp_path: Path
) -> None:
    """No .superharness/ → exit 0, write nothing."""
    project = tmp_path / "plain"
    project.mkdir()
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    result = run_bash(script, cwd=project)
    assert result.returncode == 0, result.stderr
    assert not (project / ".superharness").exists()


def test_turn_end_must_not_contain_destructive_side_effects(repo_root: Path) -> None:
    """Structural contract: session-turn-end.sh is the turn-safe Stop
    hook. It must NOT call state_writer.set_task_status, must NOT write
    handoff YAMLs via yaml.safe_dump, must NOT pause inbox via the inbox
    CLI, and must NOT pkill anything. Those behaviors belong in
    session-exit.sh (true-exit only).

    Pattern-specific (not bare-substring) so comments that *mention* the
    forbidden behavior — e.g. the docstring saying 'see session-exit.sh
    for handoffs/pkill' — don't trip the guard. Only an actual call does."""
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-turn-end.sh"
    src = script.read_text()
    # Each pattern matches the actual invocation, not prose mentions.
    forbidden = [
        (r"state_writer\.set_task_status\(", "task auto-stop is session-exit's job"),
        (r"yaml\.safe_dump\(\s*handoff", "handoff YAML writes are session-exit's job"),
        (
            r"-m\s+superharness\.engine\.inbox\s+set_status",
            "inbox pause is session-exit's job",
        ),
        (
            r"^\s*pkill\s+-TERM",
            "MCP cleanup is session-exit's job — would kill tools mid-session",
        ),
    ]
    import re

    violations = []
    for pattern, reason in forbidden:
        if re.search(pattern, src, re.MULTILINE):
            violations.append(f"matched /{pattern}/: {reason}")
    assert not violations, "session-turn-end.sh must stay turn-safe.\n  " + "\n  ".join(
        violations
    )
