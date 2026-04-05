"""Tests for parallel_dispatch and swarm modules."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _make_git_project(tmp_path: Path) -> Path:
    """Create a minimal git project for worktree tests."""
    project = tmp_path / "proj"
    project.mkdir()
    subprocess.run(["git", "init"], cwd=project, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=project, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=project, capture_output=True, check=True)
    subprocess.run(["git", "config", "core.hooksPath", "/dev/null"], cwd=project, capture_output=True, check=True)
    (project / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=project, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=project, capture_output=True, check=True)
    (project / ".superharness").mkdir()
    return project


# ---------------------------------------------------------------------------
# _sanitize_task_id
# ---------------------------------------------------------------------------

class TestSanitizeTaskId:
    def test_alphanumeric_unchanged(self) -> None:
        from superharness.engine.parallel_dispatch import _sanitize_task_id
        assert _sanitize_task_id("feat.my-task_v2") == "feat.my-task_v2"

    def test_path_traversal_rejected(self) -> None:
        from superharness.engine.parallel_dispatch import _sanitize_task_id
        result = _sanitize_task_id("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_leading_slash_stripped(self) -> None:
        from superharness.engine.parallel_dispatch import _sanitize_task_id
        result = _sanitize_task_id("/absolute/path")
        assert not result.startswith("/")

    def test_special_chars_replaced(self) -> None:
        from superharness.engine.parallel_dispatch import _sanitize_task_id
        result = _sanitize_task_id("task with spaces & $pecial")
        assert " " not in result
        assert "&" not in result
        assert "$" not in result

    def test_length_capped_at_100(self) -> None:
        from superharness.engine.parallel_dispatch import _sanitize_task_id
        result = _sanitize_task_id("a" * 200)
        assert len(result) <= 100

    def test_empty_string(self) -> None:
        from superharness.engine.parallel_dispatch import _sanitize_task_id
        result = _sanitize_task_id("")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# parallel_dispatch
# ---------------------------------------------------------------------------

class TestWorktreeCreation:
    def test_create_and_remove_worktree(self, tmp_path: Path) -> None:
        from superharness.engine.parallel_dispatch import _create_worktree, _remove_worktree
        project = _make_git_project(tmp_path)
        branch = "test/wt-1"
        wt_path = str(tmp_path / "wt-1")

        assert _create_worktree(str(project), branch, wt_path) is True
        assert os.path.isdir(wt_path)
        assert os.path.isfile(os.path.join(wt_path, "README.md"))

        _remove_worktree(str(project), wt_path, branch)
        assert not os.path.isdir(wt_path)

    def test_create_worktree_fails_gracefully(self, tmp_path: Path) -> None:
        from superharness.engine.parallel_dispatch import _create_worktree
        assert _create_worktree(str(tmp_path / "nonexistent"), "b", str(tmp_path / "wt")) is False


class TestCopySuperharness:
    def test_symlinks_superharness_dir(self, tmp_path: Path) -> None:
        from superharness.engine.parallel_dispatch import _copy_superharness_state
        project = _make_git_project(tmp_path)
        wt = tmp_path / "wt"
        wt.mkdir()

        _copy_superharness_state(str(project), str(wt))
        assert os.path.islink(str(wt / ".superharness"))


class TestFanoutResult:
    def test_fanout_result_defaults(self) -> None:
        from superharness.engine.parallel_dispatch import FanoutResult
        r = FanoutResult(slots=[])
        assert r.total_cost_usd == 0.0
        assert r.merge_conflicts == []
        assert r.winner_index is None


class TestFanoutDispatch:
    def test_fanout_creates_slots(self, tmp_path: Path) -> None:
        from superharness.engine.parallel_dispatch import fanout_dispatch, WorktreeSlot

        project = _make_git_project(tmp_path)

        # Mock SDK runner to avoid actual API calls
        mock_result = {"output": "done", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01}

        with patch("superharness.engine.parallel_dispatch._run_sdk_in_worktree") as mock_run:
            def fake_run(slot, prompt, model, budget):
                slot.status = "done"
                slot.result = mock_result
                slot.cost_usd = 0.01

            mock_run.side_effect = fake_run
            result = fanout_dispatch(str(project), "test prompt", n=2, task_id="test-fanout")

        assert len(result.slots) == 2
        assert all(s.status == "done" for s in result.slots)
        assert result.total_cost_usd == pytest.approx(0.02)

    def test_fanout_handles_failed_slots(self, tmp_path: Path) -> None:
        from superharness.engine.parallel_dispatch import fanout_dispatch

        project = _make_git_project(tmp_path)

        with patch("superharness.engine.parallel_dispatch._run_sdk_in_worktree") as mock_run:
            def fake_run(slot, prompt, model, budget):
                if slot.index == 0:
                    slot.status = "done"
                    slot.cost_usd = 0.01
                else:
                    slot.status = "failed"
                    slot.error = "timeout"

            mock_run.side_effect = fake_run
            result = fanout_dispatch(str(project), "test", n=2, task_id="test-fail")

        assert result.slots[0].status == "done"
        assert result.slots[1].status == "failed"


# ---------------------------------------------------------------------------
# swarm
# ---------------------------------------------------------------------------

class TestSwarmVerdict:
    def test_verdict_defaults(self) -> None:
        from superharness.engine.swarm import SwarmVerdict
        v = SwarmVerdict()
        assert v.winner_index is None
        assert v.merged is False
        assert v.total_cost_usd == 0.0


class TestParseReviewResult:
    def test_parses_winner_and_reasoning(self) -> None:
        from superharness.engine.swarm import _parse_review_result
        output = "WINNER: 2\nREASONING: Slot 2 has better test coverage."
        winner, reasoning = _parse_review_result(output)
        assert winner == 2
        assert "test coverage" in reasoning

    def test_handles_missing_winner(self) -> None:
        from superharness.engine.swarm import _parse_review_result
        winner, reasoning = _parse_review_result("no structured output")
        assert winner is None
        assert reasoning == ""

    def test_handles_invalid_winner(self) -> None:
        from superharness.engine.swarm import _parse_review_result
        winner, _ = _parse_review_result("WINNER: abc")
        assert winner is None


class TestBuildReviewPrompt:
    def test_includes_all_diffs(self) -> None:
        from superharness.engine.swarm import _build_review_prompt
        diffs = [
            {"index": 0, "branch": "slot-0", "stat": "1 file", "diff": "+line", "cost_usd": 0.01},
            {"index": 1, "branch": "slot-1", "stat": "2 files", "diff": "+other", "cost_usd": 0.02},
        ]
        prompt = _build_review_prompt(diffs, "fix the bug")
        assert "Slot 0" in prompt
        assert "Slot 1" in prompt
        assert "fix the bug" in prompt
        assert "WINNER:" in prompt


class TestSwarmDispatch:
    def test_swarm_single_survivor_wins(self, tmp_path: Path) -> None:
        from superharness.engine.swarm import swarm_dispatch

        project = _make_git_project(tmp_path)

        with patch("superharness.engine.swarm._run_sdk_in_worktree") as mock_run:
            def fake_run(slot, prompt, model, budget):
                if slot.index == 0:
                    slot.status = "done"
                    slot.cost_usd = 0.05
                else:
                    slot.status = "failed"
                    slot.error = "timeout"

            mock_run.side_effect = fake_run
            verdict = swarm_dispatch(str(project), "fix it", n=2, task_id="test-swarm")

        assert verdict.winner_index == 0
        assert "single survivor" in verdict.reasoning

    def test_swarm_all_fail_returns_reasoning(self, tmp_path: Path) -> None:
        from superharness.engine.swarm import swarm_dispatch

        project = _make_git_project(tmp_path)

        with patch("superharness.engine.swarm._run_sdk_in_worktree") as mock_run:
            def fake_run(slot, prompt, model, budget):
                slot.status = "failed"
                slot.error = "crash"

            mock_run.side_effect = fake_run
            verdict = swarm_dispatch(str(project), "fix it", n=2, task_id="test-allfail")

        assert verdict.winner_index is None
        assert "all workers failed" in verdict.reasoning
