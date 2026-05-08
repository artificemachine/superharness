"""E2E: a freshly-started discussion can be dispatched without the
delegate abort. Verifies the YAML→SQLite migration regression is
closed end-to-end (cmd_start creates dir → delegate's isdir check
passes → round YAML submission path is writable).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine.discussion import cmd_start


@pytest.fixture
def project(tmp_path, capsys):
    p = tmp_path / "proj"
    (p / ".superharness").mkdir(parents=True)
    conn = get_connection(str(p))
    init_db(conn, str(p))
    conn.close()
    return p


def _start_discussion(project_path) -> dict:
    discussions_dir = str(project_path / ".superharness" / "discussions")
    # Capture cmd_start's stdout via subprocess so we get the JSON cleanly
    # without fighting pytest's capsys teardown semantics.
    result = subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion", "start",
         "--discussions-dir", discussions_dir,
         "--topic", "Test topic",
         "--max-rounds", "3",
         "--project", str(project_path),
         "--created-by", "claude-code",
         "--participant", "claude-code",
         "--participant", "codex-cli"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_e2e_freshly_started_discussion_has_writable_dir(project):
    """The directory exists immediately after start, and an agent could
    write a round submission YAML into it without EEXIST/ENOENT errors."""
    disc = _start_discussion(project)
    disc_dir = disc["discussion_dir"]

    assert os.path.isdir(disc_dir), "discussion_dir must exist after start"

    # Simulate an agent writing its round-1 submission.
    submit_path = os.path.join(disc_dir, "round-1-claude-code.yaml")
    with open(submit_path, "w", encoding="utf-8") as fh:
        fh.write("verdict: agree\nposition: ok\n")
    assert os.path.isfile(submit_path)


def test_e2e_delegate_isdir_guard_passes_for_fresh_discussion(project):
    """The exact check delegate.py:990 performs — os.path.isdir on the
    discussion_dir — must succeed immediately after start. Pre-fix this
    failed and the dispatch printed 'Discussion directory not found:'."""
    disc = _start_discussion(project)
    disc_dir = disc["discussion_dir"]

    # This is the line copied verbatim from delegate.py:990.
    assert os.path.isdir(disc_dir)


def test_e2e_round_context_works_for_fresh_discussion(project):
    """The round_context engine command (called by delegate to build
    the dispatch prompt) must succeed for a discussion that has only
    just been started."""
    disc = _start_discussion(project)
    disc_dir = disc["discussion_dir"]

    result = subprocess.run(
        [sys.executable, "-m", "superharness.engine.discussion",
         "round_context",
         "--discussion-dir", disc_dir,
         "--round", "1",
         "--agent", "claude-code"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    ctx = json.loads(result.stdout)
    assert ctx["topic"] == "Test topic"
    assert ctx["round"] == 1
    assert "claude-code" in ctx.get("other_agents", []) + [ctx.get("agent")]
