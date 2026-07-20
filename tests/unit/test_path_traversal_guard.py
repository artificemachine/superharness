"""RED tests: task_id path traversal reaches makedirs and rmtree.

TOKEN_RE (commands/task.py) permits "." and "/" so that legitimate discussion
round ids like "disc-fresh/round-1" work — 51 such ids exist in a live install.
But that also admits ".." components, and task_id flows unsanitized into
inbox_dispatch._git_worktree_add, which os.path.joins it under the temp dir,
makedirs the parent, and stores the result in tasks.worktree_path. close.py
later reads that column back and shutil.rmtree's it.

Validating only at the CLI boundary is not sufficient: mcp/tools/contract.py
create_task() INSERTs an arbitrary id with no validation at all, so the
path-building sink has to defend itself.
"""
from __future__ import annotations

import os
import tempfile

import pytest

TRAVERSAL_IDS = [
    "../../../../tmp/pwn",
    "..",
    "../escape",
    "a/../../../../etc/pwn",
    "/abs/path",
]

LEGITIMATE_IDS = [
    "disc-fresh/round-1",
    "paperclip.heartbeat",
    "fk-integrity-v33",
    "t1",
]


class TestTokenValidationRejectsTraversal:
    @pytest.mark.parametrize("bad", TRAVERSAL_IDS)
    def test_validate_token_rejects_traversal(self, bad):
        """_validate_token must reject traversal, not just non-token charsets."""
        from superharness.commands.task import _validate_token

        with pytest.raises(SystemExit):
            _validate_token("task id", bad)

    @pytest.mark.parametrize("good", LEGITIMATE_IDS)
    def test_validate_token_still_accepts_real_ids(self, good):
        """Guard must not break the 51 slash-bearing discussion round ids in use."""
        from superharness.commands.task import _validate_token

        _validate_token("task id", good)  # must not raise


class TestWorktreePathIsContained:
    @pytest.mark.parametrize("bad", TRAVERSAL_IDS)
    def test_worktree_path_stays_under_temp_root(self, bad, tmp_path, monkeypatch):
        """The worktree path built from a hostile task_id must stay inside
        <tempdir>/superharness-worktrees.

        inbox_dispatch.py carries the comment 'Only safe because worktrees are
        always under tempfile.gettempdir()' — this asserts that invariant
        actually holds rather than being assumed.
        """
        from superharness.commands import inbox_dispatch

        calls: list[str] = []
        monkeypatch.setattr(inbox_dispatch.os, "makedirs",
                            lambda p, **kw: calls.append(p))

        class _Result:
            returncode = 1
            stderr = "stubbed: no real git worktree"

        monkeypatch.setattr(inbox_dispatch.subprocess, "run",
                            lambda *a, **kw: _Result())

        inbox_dispatch._git_worktree_add(str(tmp_path), bad)

        root = os.path.realpath(
            os.path.join(tempfile.gettempdir(), "superharness-worktrees")
        )
        for created in calls:
            real = os.path.realpath(created)
            assert real == root or real.startswith(root + os.sep), (
                f"task_id {bad!r} escaped the worktree root: makedirs({created!r}) "
                f"resolves to {real!r}, outside {root!r}"
            )


class TestWorktreeRemovalIsContained:
    def test_close_refuses_to_rmtree_outside_worktree_root(self, tmp_path):
        """close.py reads tasks.worktree_path straight from the DB and rmtree's
        it. A row written before this guard existed (or via the unvalidated MCP
        create_task path) can point anywhere, so removal must verify containment
        rather than trusting the stored value."""
        from superharness.commands.close import _worktree_path_is_safe

        outside = tmp_path / "precious"
        outside.mkdir()
        assert _worktree_path_is_safe(str(outside)) is False

        root = os.path.join(tempfile.gettempdir(), "superharness-worktrees")
        os.makedirs(root, exist_ok=True)
        inside = os.path.join(root, "task-abc12345")
        assert _worktree_path_is_safe(inside) is True
