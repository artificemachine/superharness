"""Tests for adapters/claude-code/hooks/session-exit.sh.

Closes the `session-exit.sh` entry in `KNOWN_UNTESTED` in
tests/contract/test_hook_test_coverage.py.

session-exit.sh is NOT a Stop hook (see its own header). It contains
the destructive session-end behaviors (task auto-stop, handoff writes,
inbox pause, MCP pkills) that must fire only on true session exit, not
on every Stop event. These tests cover the side-effects that are safe
to exercise in CI: task stopping, handoff writing, ledger, and the
no-op short-circuits. The pkill block is verified structurally
(src inspection) rather than executed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

from tests.helpers import run_bash


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _setup_project(tmp_path: Path, *, task_status: str = "in_progress") -> Path:
    """Build a minimal superharness project with one seeded task.

    Writes both contract.yaml and state.sqlite3 (the latter via the
    seed_sqlite_from_yaml helper) so the hook — which reads SQLite via
    state_reader — sees a real in-progress claude-code task to stop.
    """
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        f"id: demo\n"
        f"tasks:\n"
        f"  - id: feat-001\n"
        f"    title: Build feature one\n"
        f"    owner: claude-code\n"
        f"    status: {task_status}\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n\n")
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)
    return project


def test_session_exit_stops_in_progress_claude_task(repo_root: Path, tmp_path: Path) -> None:
    """The hook must actually flip the SQLite row to status=stopped.

    Regression for the silent-failure bug fixed 2026-08-03 (issue #92):
    the hook used to pass `stopped_reason=` and `summary=` to
    state_writer.set_task_status, which raised "no such column" —
    swallowed by the surrounding try/except, so the row never changed
    but the handoff YAML claimed it had.
    """
    project = _setup_project(tmp_path, task_status="in_progress")
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-exit.sh"
    result = run_bash(script, cwd=project, env={"SUPERHARNESS_NO_AUTO_INSTALL": "1"})
    assert result.returncode == 0, result.stderr

    from tests.helpers import get_task_from_sqlite
    task = get_task_from_sqlite(project, "feat-001")
    assert task is not None, "task feat-001 missing from SQLite"
    assert task["status"] == "stopped", f"Expected stopped, got {task['status']}"
    assert task.get("stopped_at"), "stopped_at must be set on the stopped transition"


def test_session_exit_writes_handoff_with_session_exit_phase(repo_root: Path, tmp_path: Path) -> None:
    """Handoff YAMLs from session-exit.sh must be distinguishable from
    session-stop.sh's: filename uses the `-session-exit-` infix and the
    `phase:` field is `session_exit`. This is how an operator forensically
    tells which script fired on a given session end."""
    project = _setup_project(tmp_path, task_status="in_progress")
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-exit.sh"
    result = run_bash(script, cwd=project, env={"SUPERHARNESS_NO_AUTO_INSTALL": "1"})
    assert result.returncode == 0, result.stderr

    handoffs = sorted((project / ".superharness" / "handoffs").glob("feat-001-session-exit-*.yaml"))
    assert len(handoffs) == 1, f"expected one session-exit handoff, got: {handoffs}"
    handoff = yaml.safe_load(handoffs[0].read_text())
    assert handoff["task"] == "feat-001"
    assert handoff["phase"] == "session_exit"
    assert handoff["status"] == "stopped"
    assert handoff["from"] == "claude-code"
    assert handoff["to"] == "owner"


def test_session_exit_ledger_records_task_stop(repo_root: Path, tmp_path: Path) -> None:
    """A ledger line naming the stopped task must be appended."""
    project = _setup_project(tmp_path, task_status="in_progress")
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-exit.sh"
    result = run_bash(script, cwd=project, env={"SUPERHARNESS_NO_AUTO_INSTALL": "1"})
    assert result.returncode == 0, result.stderr
    ledger = (project / ".superharness" / "ledger.md").read_text()
    assert "session-exit: task stopped (feat-001)" in ledger


def test_session_exit_skips_non_claude_tasks(repo_root: Path, tmp_path: Path) -> None:
    """A task owned by another agent must be left alone."""
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text(
        "id: demo\n"
        "tasks:\n"
        "  - id: feat-codex\n"
        "    title: Codex's task\n"
        "    owner: codex-cli\n"
        "    status: in_progress\n"
    )
    (harness / "ledger.md").write_text("# Ledger\n\n")
    from tests.helpers import seed_sqlite_from_yaml
    seed_sqlite_from_yaml(project)

    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-exit.sh"
    result = run_bash(script, cwd=project, env={"SUPERHARNESS_NO_AUTO_INSTALL": "1"})
    assert result.returncode == 0, result.stderr

    from tests.helpers import get_task_from_sqlite
    task = get_task_from_sqlite(project, "feat-codex")
    assert task is not None
    assert task["status"] == "in_progress", "session-exit must not stop non-claude tasks"


def test_session_exit_noop_without_superharness_dir(repo_root: Path, tmp_path: Path) -> None:
    """In a plain directory with no .superharness/, the hook must exit 0
    and write nothing. This is the path that fires for every Claude
    session whose project isn't superharness-managed."""
    project = tmp_path / "plain"
    project.mkdir()
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-exit.sh"
    result = run_bash(script, cwd=project)
    assert result.returncode == 0, result.stderr
    assert not (project / ".superharness").exists()


def test_session_exit_pkill_block_targets_mcp_servers_only(repo_root: Path) -> None:
    """Structural regression: the pkill block must target MCP server
    process patterns, not broad patterns that could kill unrelated work.
    The block itself is not executed in CI (it would actually kill the
    developer's running MCP servers); this test pins its shape so a
    future edit can't quietly widen the blast radius."""
    script = repo_root / "adapters" / "claude-code" / "hooks" / "session-exit.sh"
    src = script.read_text()
    # Each pkill must use -f (full cmdline match) and a specific MCP pattern.
    pkill_lines = [ln for ln in src.splitlines() if ln.strip().startswith("pkill ")]
    assert pkill_lines, "session-exit.sh must contain the MCP cleanup pkill block"
    for ln in pkill_lines:
        assert "-TERM" in ln, f"pkill must use -TERM (graceful): {ln!r}"
        assert "-f" in ln, f"pkill must use -f (full cmdline match, safer): {ln!r}"
        # Forbidden: broad pkill patterns that could kill unrelated work
        assert not ln.strip().endswith("pkill python3"), f"too broad: {ln!r}"
        assert "pkill -9" not in ln, f"pkill -9 is not graceful: {ln!r}"
