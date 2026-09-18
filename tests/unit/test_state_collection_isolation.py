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

So these tests are not a fix's proof of failure; they are the kept proof that the
property holds, so a future import-time state access cannot reintroduce the escape
unnoticed. `tests/conftest.py` is deliberately unchanged: the per-test
`isolated_state_dir` fixture already covers test bodies, and nothing here found a
collection-time gap to close.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# The two ways a project can pin its state root. Both must be cleared so the child
# resolves state the way an ordinary developer invocation would: under HOME.
_STATE_ROOT_ENV = ("XDG_STATE_HOME", "SUPERHARNESS_STATE_DIR")


def _child_env(home: Path, **extra: str) -> dict[str, str]:
    env = {**os.environ, "HOME": str(home)}
    for name in _STATE_ROOT_ENV:
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
