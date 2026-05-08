"""Regression: engine.discussion.cmd_start must create the filesystem
discussion directory.

Background: discussions migrated YAML→SQLite, but cmd_start stopped
creating the directory while delegate.py still requires it (and agents
still write round-N-<agent>.yaml into it). Result: every post-migration
discussion fails to dispatch with 'Discussion directory not found',
triggering the auto-recover runaway loop we observed at max_retries=65.
"""
from __future__ import annotations

import os

from superharness.engine.db import get_connection, init_db
from superharness.engine.discussion import cmd_start


def _setup(tmp_path):
    project = tmp_path / "proj"
    sh = project / ".superharness"
    sh.mkdir(parents=True)
    conn = get_connection(str(project))
    init_db(conn, str(project))
    conn.close()
    return project


def test_cmd_start_creates_discussion_directory(tmp_path, capsys):
    project = _setup(tmp_path)
    discussions_dir = str(project / ".superharness" / "discussions")

    rc = cmd_start(
        discussions_dir=discussions_dir,
        topic="t",
        participants=["claude-code", "codex-cli"],
        max_rounds=3,
        task_id=None,
        project=str(project),
        created_by="claude-code",
    )
    assert rc == 0

    captured = capsys.readouterr()
    import json
    out = json.loads(captured.out)
    disc_dir = out["discussion_dir"]

    assert os.path.isdir(disc_dir), (
        f"cmd_start must create discussion_dir on disk; "
        f"reported {disc_dir} but it does not exist"
    )


def test_cmd_start_is_idempotent_on_directory_creation(tmp_path):
    """If the directory already exists (rerun, manual mkdir, etc.)
    cmd_start must not crash on EEXIST."""
    project = _setup(tmp_path)
    discussions_dir = str(project / ".superharness" / "discussions")
    os.makedirs(discussions_dir, exist_ok=True)
    # Pre-create a sibling dir to make sure we don't accidentally collide.
    os.makedirs(os.path.join(discussions_dir, "unrelated"), exist_ok=True)

    rc = cmd_start(
        discussions_dir=discussions_dir,
        topic="t",
        participants=["claude-code", "codex-cli"],
        max_rounds=3,
        task_id=None,
        project=str(project),
        created_by="claude-code",
    )
    assert rc == 0
