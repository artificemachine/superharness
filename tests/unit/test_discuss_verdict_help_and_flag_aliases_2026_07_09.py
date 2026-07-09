"""Regression tests for 2026-07-09 discuss CLI UX bugs, found while reviewing
a two-agent discussion transcript.

Covers two bugs:

- Bug N: `discuss submit --help` documented only 3 of the 5 valid --verdict
  values (`consensus|disagree|abstain`), while the discussion-start template
  and the actual validator both accept `agree` and `partial` too. An agent
  following --help literally cannot express agreement or partial agreement.
- Bug O: `--id` and `--discussion` were not interchangeable across the five
  discussion-scoped subcommands — `rounds`/`consensus`/`summary`/`close`
  only accepted `--id`, `submit` only accepted `--discussion`. Every
  cross-subcommand invocation was a guess.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT


def _run_discuss(cwd: Path, args: list[str]) -> subprocess.CompletedProcess:
    env = {**__import__("os").environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.discuss"] + args,
        cwd=str(cwd), text=True, capture_output=True, env=env, check=False,
    )


def _assert_clean_argparse(result: subprocess.CompletedProcess) -> None:
    """A clean parse hits business logic ('Discussion not found', rc=1), not
    argparse's own usage/error exit (rc=2). rc=2 means the flag was rejected
    or a genuinely required argument is still missing."""
    assert result.returncode != 2, (
        f"argparse rejected the invocation (rc=2):\n{result.stderr}"
    )
    assert "unrecognized arguments" not in result.stderr, result.stderr
    assert "the following arguments are required" not in result.stderr, result.stderr


# ---------------------------------------------------------------------------
# Bug N — --verdict help text omits agree/partial
# ---------------------------------------------------------------------------

class TestBugN_VerdictHelpMismatch:
    def test_submit_help_lists_all_valid_verdicts(self):
        """--help for `discuss submit` must list every value the validator
        (superharness.engine.discussion, valid_verdicts) actually accepts."""
        result = _run_discuss(REPO_ROOT, ["submit", "--help"])
        assert result.returncode == 0, result.stderr
        for verdict in ("agree", "disagree", "partial", "consensus", "abstain"):
            assert verdict in result.stdout, (
                f"--verdict help text missing '{verdict}': {result.stdout}"
            )


# ---------------------------------------------------------------------------
# Bug O — --id / --discussion not interchangeable
# ---------------------------------------------------------------------------

class TestBugO_IdDiscussionFlagAlias:
    """rounds/consensus/summary/close natively accept --id; --discussion must
    now work as an alias. submit natively accepts --discussion; --id must
    now work as an alias. 'Discussion not found' + rc=1 is the expected
    outcome for a fake id once the flag itself is accepted."""

    @pytest.mark.parametrize("subcmd", ["rounds", "consensus", "summary", "close"])
    def test_id_native_subcommand_accepts_discussion_alias(self, subcmd):
        result = _run_discuss(REPO_ROOT, [subcmd, "--discussion", "disc-test-123"])
        _assert_clean_argparse(result)

    @pytest.mark.parametrize("subcmd", ["rounds", "consensus", "summary", "close"])
    def test_id_native_subcommand_still_accepts_id(self, subcmd):
        result = _run_discuss(REPO_ROOT, [subcmd, "--id", "disc-test-123"])
        _assert_clean_argparse(result)

    def test_submit_accepts_id_alias(self):
        result = _run_discuss(REPO_ROOT, [
            "submit", "--id", "disc-test-123",
            "--agent", "claude-code", "--round", "1",
            "--verdict", "agree", "--position", "test",
        ])
        _assert_clean_argparse(result)

    def test_submit_still_accepts_discussion(self):
        result = _run_discuss(REPO_ROOT, [
            "submit", "--discussion", "disc-test-123",
            "--agent", "claude-code", "--round", "1",
            "--verdict", "agree", "--position", "test",
        ])
        _assert_clean_argparse(result)
