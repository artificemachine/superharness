"""Iteration 1 of ``docs/PLAN-state-db-skeleton-leak.md``: collection isolation.

*"Garantir l'isolation avant collecte et dans les sous-processus"* — and, per the
same iteration, *"si aucune fuite n'est reproduite, arrêt pour réviser"*.

**Measured on this revision: no collection-time escape.** Collecting this suite
with a synthetic `HOME` and no `XDG_STATE_HOME` / `SUPERHARNESS_STATE_DIR`
override creates zero `state.db` files anywhere under that HOME (it creates
`<HOME>/Library/Logs/superharness`, a log directory, which is not state). The
plan's own prerequisites recorded the same caveat — the growth reported in
BUG-2026-09-18 was never reproduced *against this revision*, and archived
databases are not evidence about it.

Two properties are pinned, and they were measured separately.

**State**: collecting this suite with a synthetic `HOME` creates zero `state.db`
files under it. That is the negative result described above — no fix was needed.

**Logs**: collection wrote `<HOME>/Library/Logs/superharness/superharness.log`
(0 bytes), because `logging_utils._default_log_dir()` resolves from
`Path.home()` on macOS and `_ensure_handler()` creates the directory. No per-test
fixture can cover that: it happens during collection, before any fixture is
active. `tests/conftest.py` therefore installs a session `SUPERHARNESS_LOG_FILE`
/ `SUPERHARNESS_AUDIT_LOG_FILE` at import time, which is the earliest point that
covers collection and is inherited by spawned subprocesses. Production log
resolution is untouched — `<HOME>/Library/Logs` is the macOS convention and changing it
would be a user-visible behaviour change that this defect does not justify.

The children below deliberately inherit none of these overrides, so what they
exercise is the repository's isolation, not the parent's environment.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# Overrides the child must not inherit, so that it resolves state and logs the
# way a plain developer invocation would. Any isolation has to come from the
# repository's own conftest.py, or these tests would be asserting the parent's
# environment instead of the repository's behaviour.
_INHERITED_OVERRIDES = (
    "XDG_STATE_HOME",
    "SUPERHARNESS_STATE_DIR",
    "SUPERHARNESS_LOG_FILE",
    "SUPERHARNESS_AUDIT_LOG_FILE",
)


def _child_env(home: Path, **extra: str) -> dict[str, str]:
    env = {**os.environ, "HOME": str(home)}
    for name in _INHERITED_OVERRIDES:
        env.pop(name, None)
    env.update(extra)
    return env


def _state_databases(root: Path) -> list[str]:
    return sorted(str(p) for p in root.rglob("state.db"))


def test_collection_state_stays_in_session_root(tmp_path):
    """Two successive collections must leave the synthetic HOME free of state.

    Acceptance criterion: "Deux exécutions successives ne laissent aucune base
    dans le HOME synthétique." Collection is where a module-level import could
    touch state before any fixture is active, so it is the path worth pinning.
    """
    home = tmp_path / "synthetic-home"
    home.mkdir()

    for attempt in (1, 2):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
            cwd=REPO,
            env=_child_env(home),
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert result.returncode == 0, (
            f"collection run {attempt} failed:\n{result.stdout[-2000:]}\n"
            f"{result.stderr[-2000:]}"
        )

        leaked = _state_databases(home)
        assert leaked == [], (
            f"collection run {attempt} wrote state into the synthetic HOME: {leaked}"
        )


def test_child_state_is_cleaned_after_session(tmp_path):
    """A child pytest honours the inherited state root and leaves nothing in HOME.

    Proves inheritance (the child writes where the parent pointed it rather than
    into HOME) and that nothing persists outside the ephemeral root once the
    session closes.
    """
    home = tmp_path / "synthetic-home"
    home.mkdir()
    session_state = tmp_path / "session-state"

    child_test = tmp_path / "test_child_writes_state.py"
    child_test.write_text(
        "from superharness.engine.db import get_connection, init_db\n"
        "\n"
        "\n"
        "def test_opens_state():\n"
        "    conn = get_connection('/nonexistent/synthetic-project')\n"
        "    try:\n"
        "        init_db(conn)\n"
        "        conn.commit()\n"
        "    finally:\n"
        "        conn.close()\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", child_test.name],
        cwd=tmp_path,
        env=_child_env(home, XDG_STATE_HOME=str(session_state)),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"child pytest failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )

    written = _state_databases(session_state)
    assert written, (
        "the child did not write into the inherited XDG_STATE_HOME, so inheritance "
        "is not actually being exercised"
    )
    assert _state_databases(home) == [], (
        "the child escaped the inherited state root into HOME"
    )

    # Removing the ephemeral root is the cleanup step: nothing may survive it.
    import shutil

    shutil.rmtree(session_state, ignore_errors=True)
    assert not session_state.exists(), "the session state root could not be removed"
    assert _state_databases(home) == [], "state survived in HOME after cleanup"


def test_collection_writes_nothing_into_home(tmp_path):
    """Acceptance criterion: collection writes only into temporary space.

    Not even a log directory may appear. This is the check that found a real
    escape: `logging_utils._ensure_handler()` created
    `<HOME>/Library/Logs/superharness/superharness.log` during collection, because
    `_default_log_dir()` resolves from `Path.home()` on macOS and no fixture is
    active at that point.
    """
    home = tmp_path / "synthetic-home"
    home.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "tests/"],
        cwd=REPO,
        env=_child_env(home),
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert result.returncode == 0, (
        f"collection failed:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
    )

    leftovers = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
    assert leftovers == [], f"collection wrote into the synthetic HOME: {leftovers}"
