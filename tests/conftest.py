from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, SCRIPTS_DIR, seed_sqlite_from_yaml

# Ensure shims (SUPERHARNESS_PYTHON shim pattern) always resolve to the interpreter
# running the test suite, even when individual tests restrict PATH to /usr/bin:/bin.
os.environ.setdefault("SUPERHARNESS_PYTHON", sys.executable)


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
