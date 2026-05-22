"""Tests for Bug T fix: _reconcile_state() must not pause discussion items on dirty worktree.

Root cause: when gemini-cli exits rc=0 but could not write its submission YAML
(write_file blocked), _reconcile_state() is called. If ctx.is_discussion and the YAML
is absent, final_state stays "" and the fallback dirty-worktree branch incorrectly sets
the item to 'paused'. The item then waits 30 min for the lifecycle rule before retrying.

Fix: for discussion items with no YAML on disk:
  1. Try _recover_yaml_from_log() (Bug S extension to rc=0 path)
  2. If recovery fails, set final_state = "failed" immediately (no dirty-worktree check)
"""

import os
import time
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import yaml

from superharness.commands.inbox_dispatch import _reconcile_state


DISC_ID = "discuss-20260522T084340Z-99999-000000"
ROUND = 2
AGENT = "gemini-cli"
ROUND_SLUG = f"round-{ROUND}"

VALID_SUBMISSION = {
    "discussion_id": DISC_ID,
    "round": ROUND,
    "agent": AGENT,
    "verdict": "partial",
    "rationale": "Gaps remain.",
    "submitted_at": "2026-05-22T10:00:00Z",
}

# Patches required by every test — mock SQLite side-effects that need a real DB.
_SIDE_PATCHES = [
    "superharness.commands.inbox_dispatch._sqlite_record_review",
    "superharness.commands.inbox_dispatch._sqlite_mirror_dispatch",
    "superharness.commands.inbox_dispatch._set_inbox_field",
]


def _make_ctx(tmp_path, *, has_log: bool = False, log_content: str = ""):
    """Build a minimal DispatchContext mock for a discussion round."""
    ctx = MagicMock()
    ctx.non_interactive = True
    ctx.print_only = False
    ctx.is_discussion = True
    ctx.item_task = f"{DISC_ID}/{ROUND_SLUG}"
    ctx.item_to = AGENT
    ctx.exec_project = str(tmp_path)
    ctx.project_dir = str(tmp_path)
    ctx.item_id = "inbox-item-abc"
    ctx.inbox_file = str(tmp_path / "inbox.yaml")
    ctx.launch_start = time.time()  # real float so _sqlite_record_review can compute duration

    log_path = str(tmp_path / "launcher.log")
    if has_log:
        with open(log_path, "w") as fh:
            fh.write(log_content)
    ctx.task_log = log_path

    ctx.contract_file = str(tmp_path / "contract.yaml")
    return ctx


def _submission_path(tmp_path) -> str:
    d = tmp_path / ".superharness" / "discussions" / DISC_ID
    return str(d / f"{ROUND_SLUG}-{AGENT}.yaml")


def _run(ctx, *, extra_patches=None):
    """Call _reconcile_state with standard mocks + optional extras."""
    statuses: list[tuple] = []

    def fake_set_status(inbox_file, item_id, from_s, to_s, ts, ts_field):
        statuses.append((from_s, to_s))
        return True

    with ExitStack() as stack:
        mock_lock = stack.enter_context(
            patch("superharness.commands.inbox_dispatch._MkdirLock")
        )
        mock_lock.return_value.acquire_with_retry = lambda *a: True
        mock_lock.return_value.release = lambda: None

        stack.enter_context(
            patch("superharness.commands.inbox_dispatch._set_inbox_status",
                  side_effect=fake_set_status)
        )
        for p in _SIDE_PATCHES:
            stack.enter_context(patch(p))
        for name, kwargs in (extra_patches or []):
            stack.enter_context(patch(name, **kwargs))

        _reconcile_state(ctx)

    return [to for _, to in statuses]


# ---------------------------------------------------------------------------
# Bug T: no YAML, no log → must set final_state = "failed" (not "paused")
# ---------------------------------------------------------------------------

class TestBugT_NoYamlNoLog:
    def test_discussion_no_yaml_goes_to_failed_not_paused(self, tmp_path):
        """With no YAML on disk and no log, item must be failed immediately."""
        ctx = _make_ctx(tmp_path, has_log=False)
        target_statuses = _run(
            ctx,
            extra_patches=[
                ("superharness.commands.inbox_dispatch._has_dirty_worktree",
                 {"return_value": True}),
            ],
        )
        assert "failed" in target_statuses, f"Expected 'failed' in {target_statuses}"
        assert "paused" not in target_statuses, f"Unexpected 'paused' in {target_statuses}"

    def test_dirty_worktree_check_not_called_for_discussion(self, tmp_path):
        """_has_dirty_worktree must never be consulted for discussion items."""
        ctx = _make_ctx(tmp_path, has_log=False)

        with ExitStack() as stack:
            mock_lock = stack.enter_context(
                patch("superharness.commands.inbox_dispatch._MkdirLock")
            )
            mock_lock.return_value.acquire_with_retry = lambda *a: True
            mock_lock.return_value.release = lambda: None
            stack.enter_context(
                patch("superharness.commands.inbox_dispatch._set_inbox_status",
                      return_value=True)
            )
            for p in _SIDE_PATCHES:
                stack.enter_context(patch(p))
            mock_dirty = stack.enter_context(
                patch("superharness.commands.inbox_dispatch._has_dirty_worktree",
                      return_value=True)
            )
            _reconcile_state(ctx)

        mock_dirty.assert_not_called()


# ---------------------------------------------------------------------------
# Bug S (rc=0 path): YAML in log → recover, then mark done
# ---------------------------------------------------------------------------

class TestBugS_RecoverFromLog:
    def test_discussion_yaml_in_log_marks_done(self, tmp_path):
        """When YAML is recoverable from the log, final_state must be 'done'."""
        block = yaml.dump(VALID_SUBMISSION, allow_unicode=True, default_flow_style=False)
        log_content = "Error: write_file not available\n```yaml\n" + block + "```\n"
        ctx = _make_ctx(tmp_path, has_log=True, log_content=log_content)
        target_statuses = _run(ctx)
        assert "done" in target_statuses, f"Expected 'done' in {target_statuses}"
        assert "failed" not in target_statuses
        assert "paused" not in target_statuses

    def test_recovered_yaml_written_to_disk(self, tmp_path):
        """Recovered YAML must be written to the submission path on disk."""
        block = yaml.dump(VALID_SUBMISSION, allow_unicode=True, default_flow_style=False)
        log_content = "```yaml\n" + block + "```\n"
        ctx = _make_ctx(tmp_path, has_log=True, log_content=log_content)
        _run(ctx)

        submission_path = _submission_path(tmp_path)
        assert os.path.isfile(submission_path), "Submission YAML must be on disk after recovery"
        data = yaml.safe_load(open(submission_path).read())
        assert data["verdict"] == "partial"
        assert data["agent"] == AGENT

    def test_invalid_log_content_falls_back_to_failed(self, tmp_path):
        """A log with invalid/wrong YAML must still mark the item failed, not paused."""
        log_content = "```yaml\nagent: wrong-agent\nverdict: agree\n```\n"
        ctx = _make_ctx(tmp_path, has_log=True, log_content=log_content)
        target_statuses = _run(
            ctx,
            extra_patches=[
                ("superharness.commands.inbox_dispatch._has_dirty_worktree",
                 {"return_value": True}),
            ],
        )
        assert "failed" in target_statuses
        assert "paused" not in target_statuses


# ---------------------------------------------------------------------------
# Regression: YAML on disk still works as before
# ---------------------------------------------------------------------------

class TestRegression_YamlOnDisk:
    def test_yaml_on_disk_still_marks_done(self, tmp_path):
        """Existing behavior: if YAML is already on disk, item must be done."""
        submission_path = _submission_path(tmp_path)
        os.makedirs(os.path.dirname(submission_path), exist_ok=True)
        with open(submission_path, "w") as fh:
            yaml.dump(VALID_SUBMISSION, fh)

        ctx = _make_ctx(tmp_path, has_log=False)
        target_statuses = _run(ctx)
        assert "done" in target_statuses
        assert "failed" not in target_statuses
        assert "paused" not in target_statuses


# ---------------------------------------------------------------------------
# Regression: non-discussion items with dirty worktree still pause (unchanged)
# ---------------------------------------------------------------------------

class TestRegression_NonDiscussionDirtyWorktree:
    def test_non_discussion_dirty_worktree_still_pauses(self, tmp_path):
        """Non-discussion items must still pause on dirty worktree (no regression)."""
        ctx = _make_ctx(tmp_path, has_log=False)
        ctx.is_discussion = False
        contract = tmp_path / "contract.yaml"
        contract.write_text("tasks: []\n")
        ctx.contract_file = str(contract)

        with ExitStack() as stack:
            mock_lock = stack.enter_context(
                patch("superharness.commands.inbox_dispatch._MkdirLock")
            )
            mock_lock.return_value.acquire_with_retry = lambda *a: True
            mock_lock.return_value.release = lambda: None

            statuses: list[tuple] = []

            def fake_set_status(inbox_file, item_id, from_s, to_s, ts, ts_field):
                statuses.append((from_s, to_s))
                return True

            stack.enter_context(
                patch("superharness.commands.inbox_dispatch._set_inbox_status",
                      side_effect=fake_set_status)
            )
            for p in _SIDE_PATCHES:
                stack.enter_context(patch(p))
            stack.enter_context(
                patch("superharness.commands.inbox_dispatch._has_dirty_worktree",
                      return_value=True)
            )
            mock_run = stack.enter_context(
                patch("superharness.commands.inbox_dispatch.subprocess.run")
            )
            # contract task_status returns an unknown state → falls to the else branch
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "unknown_state"

            _reconcile_state(ctx)

        target_statuses = [to for _, to in statuses]
        assert "paused" in target_statuses, (
            "Non-discussion items on dirty worktree must still be paused"
        )
