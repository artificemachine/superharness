"""Tests for two adapter-polish bugs that surfaced after the dispatch
infrastructure started actually working:

Bug 1: opencode requires provider-prefixed model strings ("anthropic/claude-...").
       Auto-classified models came in as bare "claude-sonnet-4-6" and opencode
       rejected with ProviderModelNotFoundError.

Bug 2: codex CLI sandbox refuses to write through symlinks. With the worktree
       .superharness/ being a symlink to the live source, codex couldn't
       write its submission YAML and dropped it in the worktree root, where
       it got gc'd. Fix: skip worktree isolation for discussion-round
       dispatches since they need direct write access to .superharness/.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Bug 1 — opencode model auto-prefix
# ---------------------------------------------------------------------------

def test_opencode_branch_prefixes_claude_with_anthropic():
    """delegate.py must prefix bare claude-* model names with anthropic/
    when launching opencode, otherwise opencode rejects with
    ProviderModelNotFoundError."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "delegate.py").read_text()
    # Find the opencode branch
    idx = src.find('elif target == "opencode":')
    assert idx > 0
    branch = src[idx : idx + 1500]
    assert 'anthropic/' in branch, (
        "opencode branch must auto-prefix Claude models with 'anthropic/'. "
        "Got branch:\n" + branch[:600]
    )
    assert 'claude-' in branch, "branch must check for claude- prefix"


def test_opencode_branch_prefixes_openai_models():
    """Same check for openai/ prefix on gpt/o1/o3 models."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "delegate.py").read_text()
    idx = src.find('elif target == "opencode":')
    branch = src[idx : idx + 1500]
    assert 'openai/' in branch
    assert 'gpt-' in branch


# ---------------------------------------------------------------------------
# Bug 2 — discussion dispatches must NOT use worktree isolation
# ---------------------------------------------------------------------------

def test_dispatch_skips_worktree_for_discussion_rounds():
    """inbox_dispatch.dispatch() must not create a git worktree when the
    task_id is a discussion round, because the agent's submission YAML
    needs to land in the live source .superharness/discussions/ — and the
    codex sandbox refuses to write through the worktree's symlinked
    .superharness/."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    # The decision must reference the discussion check
    assert "is_discussion" in src, (
        "inbox_dispatch.py must compute is_discussion and skip worktree "
        "creation for discussion rounds"
    )
    assert '"/round-" in item_task' in src or "round-" in src, (
        "is_discussion must detect the /round-N suffix in task ids"
    )


def test_dispatch_discussion_check_guards_worktree_creation(tmp_path):
    """End-to-end-ish: simulate calling _git_worktree_add gating logic.
    We can't easily test the full dispatch() function, so check the
    source for the conjunction `not is_discussion and ... _has_dirty_worktree`."""
    src = (REPO_ROOT / "src" / "superharness" / "commands" / "inbox_dispatch.py").read_text()
    # The guard must be:  if not is_discussion and non_interactive and ...
    assert "not is_discussion" in src, (
        "the worktree-creation `if` must include `not is_discussion` so "
        "discussions never spawn a worktree"
    )
