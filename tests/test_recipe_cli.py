"""shux recipe — CLI-level tests (CONTRIBUTING.md: new CLI commands need at
least one unit test invoking the command via subprocess)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{REPO / 'src'}{os.pathsep}{env.get('PYTHONPATH', '')}"
    # A dead port: every path must fail LOUD and CLEAN, never a traceback.
    env["RMDI_ROUTER_URL"] = "http://127.0.0.1:9"
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.recipe", *args],
        capture_output=True, text=True, timeout=60, env=env,
    )


def test_recipe_list_router_down_is_clean_and_nonzero():
    res = _run("list")
    assert res.returncode == 1
    assert "RMDI router unreachable" in res.stderr
    assert "Traceback" not in res.stderr
    # The escape hatch is the EPHEMERAL env var, not a durable profile edit.
    assert "SUPERHARNESS_ROUTING_STRATEGY=native" in res.stderr


def test_recipe_events_router_down_is_clean():
    res = _run("events", "--limit", "5")
    assert res.returncode == 1
    assert "Traceback" not in res.stderr


def test_recipe_bad_limit_exits_2():
    res = _run("events", "--limit", "many")
    assert res.returncode == 2
