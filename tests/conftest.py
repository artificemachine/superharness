from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, SCRIPTS_DIR, seed_sqlite_from_yaml

# Ensure subprocesses spawned by tests can always import superharness from the repo
# source tree, regardless of whether it is pip-installed in the active interpreter.
# Tests that set PYTHONPATH explicitly (e.g. test_delegate.py) already do this;
# this setdefault covers the ones that rely on bare sys.executable without a PYTHONPATH.
_src = str(REPO_ROOT / "src")
os.environ["PYTHONPATH"] = _src + os.pathsep + os.environ.get("PYTHONPATH", "")

# Ensure shims (SUPERHARNESS_PYTHON shim pattern) always resolve to the interpreter
# running the test suite, even when individual tests restrict PATH to /usr/bin:/bin.
os.environ.setdefault("SUPERHARNESS_PYTHON", sys.executable)

# Block tests from auto-installing real LaunchAgents on the user's system.
# session-start.sh and friends honor this flag and skip ensure-launchd-inbox-watcher.sh.
os.environ["SUPERHARNESS_NO_AUTO_INSTALL"] = "1"


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path_factory, monkeypatch):
    """Point SUPERHARNESS_STATE_DIR at a per-test directory.

    `get_connection(project_dir)` resolves the db to
    `<state_dir>/<sha256(abspath(project_dir))[:12]>/state.db`. `state_dir`
    defaults to `~/.local/state/superharness`, which lives outside `tmp_path`
    and persists indefinitely.

    `tmp_path` sits under the OS temp root, which macOS purges periodically.
    After a purge pytest's `pytest-N` counter restarts, so a later run can hand
    a test the same `tmp_path` string it used before. The state dir keyed on
    that path still exists, so a "fresh" `tmp_path` silently reopens a stale
    database — producing `UNIQUE constraint failed: inbox.id` on any test that
    inserts a fixed primary key. It also leaked 30k+ directories into $HOME.

    Set via the environment (not just in-process) because many tests spawn
    `python -m superharness...` subprocesses that inherit os.environ.
    """
    state_dir = tmp_path_factory.mktemp("superharness-state")
    monkeypatch.setenv("SUPERHARNESS_STATE_DIR", str(state_dir))
    yield state_dir


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture
def clean_harness(tmp_path: Path) -> Path:
    """Create a clean .superharness/ workspace under tmp_path with valid empty state.

    Returns the project root (parent of .superharness/). Used by lifecycle,
    state-consistency, and reconciler tests for isolated runs.
    """
    project = tmp_path / "project"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "contract.yaml").write_text("tasks: []\n")
    (harness / "inbox.yaml").write_text("# Delegation inbox\n")
    (harness / "profile.yaml").write_text(
        "auto_dispatch: false\n"
        "autonomy: manual\n"
        "auto_close: false\n"
        "auto_retry: false\n"
        "default_preset: implementation\n"
        "require_tdd: true\n"
        "auto_approve_plans: false\n"
        "paused_timeout_minutes: 30\n"
        "review_timeout_minutes: 120\n"
    )
    (harness / "handoffs").mkdir()
    (harness / "discussions").mkdir()
    # Seed SQLite from YAML so sqlite_only code paths find expected data
    seed_sqlite_from_yaml(project)
    return project


def past_iso(minutes_ago: int) -> str:
    """Return an ISO-8601 UTC timestamp `minutes_ago` minutes before now.

    Used to set up timeout-related test fixtures without needing time-mocking
    libraries. Example: `paused_at=past_iso(31)` to test a 30-minute timeout.
    """
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
