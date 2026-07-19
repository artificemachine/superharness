from __future__ import annotations

import os
import sys
import tempfile
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


def _assert_ephemeral_state_dir() -> None:
    """Fail fast if SUPERHARNESS_STATE_DIR does not point at an ephemeral tmp path.

    Defense-in-depth against the PR #12 bug class (test state leaking into
    $HOME / a real ~/.local/state/superharness). `isolated_state_dir` above
    already pins every test to a `tmp_path_factory` directory; this guard
    exists so a test that deliberately (or accidentally) overrides
    SUPERHARNESS_STATE_DIR to a non-ephemeral path fails loudly before any
    DB write, instead of silently mutating real state.
    """
    raw = os.environ.get("SUPERHARNESS_STATE_DIR")
    if not raw:
        raise RuntimeError(
            "SUPERHARNESS_STATE_DIR is unset — tests must pin state dir to an "
            "ephemeral tmp path (see isolated_state_dir fixture in conftest.py)"
        )
    resolved = Path(raw).resolve()
    resolved_str = str(resolved)
    tmp_root = str(Path(tempfile.gettempdir()).resolve())
    is_ephemeral = (
        resolved_str.startswith(tmp_root)
        or resolved_str.startswith("/tmp")
        or resolved_str.startswith("/private/tmp")
        or any(part.startswith("pytest-") for part in resolved.parts)
    )
    if not is_ephemeral:
        raise RuntimeError(
            f"SUPERHARNESS_STATE_DIR resolves to a non-ephemeral path: "
            f"{resolved_str!r}. Tests must target a tmp_path-derived "
            "directory, never a real state directory."
        )


@pytest.fixture(autouse=True)
def _state_dir_guardrail(isolated_state_dir):
    """Autouse guard run after isolated_state_dir sets an ephemeral env var.

    Function-scoped (not session-scoped): it must run after per-test env
    setup, and must observe overrides individual tests make to
    SUPERHARNESS_STATE_DIR via monkeypatch.
    """
    _assert_ephemeral_state_dir()
    yield


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


@pytest.fixture(scope="session", autouse=True)
def _launchd_leak_guard():
    """Fail the whole suite if any test leaves a NEW com.superharness.*
    launchd label behind (PLAN-superharness-L5.md iteration 5).

    Real, observed regression: a `com.superharness.inbox.worker-proj` job
    pointing at a deleted pytest tmp dir was found live on 2026-07-12, left
    by a pre-rewrite watcher-install test that ran the real install script
    without faking launchctl. Darwin-only; opt-in strict mode via
    SUPERHARNESS_STRICT_LAUNCHD_GUARD=1 so CI on non-darwin runners (which
    have no launchctl at all) is unaffected either way.
    """
    if sys.platform != "darwin":
        yield
        return
    import shutil
    if not shutil.which("launchctl"):
        yield
        return

    from tests.unit.test_launchd_test_pollution import find_leaked_labels, _current_labels

    before = _current_labels()
    yield
    after = _current_labels()
    leaked = find_leaked_labels(before, after)
    if leaked and os.environ.get("SUPERHARNESS_STRICT_LAUNCHD_GUARD") == "1":
        raise AssertionError(f"test suite leaked launchd label(s): {leaked}")
    elif leaked:
        print(f"\nWARN: test suite leaked launchd label(s): {leaked}", file=sys.stderr)


def past_iso(minutes_ago: int) -> str:
    """Return an ISO-8601 UTC timestamp `minutes_ago` minutes before now.

    Used to set up timeout-related test fixtures without needing time-mocking
    libraries. Example: `paused_at=past_iso(31)` to test a 30-minute timeout.
    """
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
