"""Regression test for 2026-07-09: `--points-file` was dead code.

`cmd_submit_round` parsed the YAML into a local `points` list and never
passed it to `discussions_dao.add_round` — there is no `points` column on
`discussion_rounds`, so per-point verdicts were silently discarded. An
agent (or operator) passing `--points-file` had every reason to believe
its point-by-point verdicts were recorded and would drive action-item
extraction. They were not; only the single round-level `--verdict` ever
mattered.

A flag that silently discards its input is worse than no flag, so it was
removed rather than reimplemented. If per-point verdicts are wanted later
they need a schema migration and a deliberate design for how they feed
`_create_consensus_task`.
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

from tests.helpers import REPO_ROOT


def _run(module: str, args: list[str]) -> subprocess.CompletedProcess:
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", module] + args,
        cwd=str(REPO_ROOT), text=True, capture_output=True, env=env, check=False,
    )


def test_submit_help_no_longer_advertises_points_file():
    result = _run("superharness.commands.discuss", ["submit", "--help"])
    assert result.returncode == 0, result.stderr
    assert "--points-file" not in result.stdout, (
        "--points-file was removed as dead code but is still advertised in --help"
    )


def test_submit_rejects_points_file_flag():
    """Passing the removed flag must fail loudly, not be silently ignored."""
    result = _run("superharness.commands.discuss", [
        "submit", "--discussion", "d-1", "--agent", "claude-code",
        "--round", "1", "--verdict", "agree", "--position", "p",
        "--points-file", "/tmp/nonexistent.yaml",
    ])
    assert result.returncode == 2, (
        f"removed flag should be rejected by argparse, got rc={result.returncode}"
    )
    assert "unrecognized arguments" in result.stderr, result.stderr


def test_cmd_submit_round_has_no_points_file_parameter():
    from superharness.engine.discussion import cmd_submit_round
    params = inspect.signature(cmd_submit_round).parameters
    assert "points_file" not in params, (
        f"cmd_submit_round still takes points_file: {list(params)}"
    )


def test_engine_discussion_module_defines_no_points_file_flag():
    """The engine module's subcommand is `submit_round` (not `submit`), and it
    prints its usage line to stderr on a bad invocation. Assert on that usage
    line so this test cannot pass vacuously."""
    result = _run("superharness.engine.discussion", ["submit_round", "--help"])
    combined = result.stdout + result.stderr
    assert "usage:" in combined, f"expected a usage line to assert against:\n{combined}"
    assert "--points-file" not in combined, (
        "engine.discussion still exposes the removed --points-file flag"
    )
