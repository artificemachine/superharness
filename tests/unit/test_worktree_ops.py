"""Tests for the shared worktree_ops module."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_sanitize_task_id_basic():
    from superharness.engine.worktree_ops import sanitize_task_id

    assert sanitize_task_id("task-001") == "task-001"
    assert sanitize_task_id("my task!") == "my-task-"


def test_sanitize_task_id_path_traversal():
    from superharness.engine.worktree_ops import sanitize_task_id

    result = sanitize_task_id("../etc/passwd")
    assert ".." not in result
    assert not result.startswith("/")


def test_sanitize_task_id_max_length():
    from superharness.engine.worktree_ops import sanitize_task_id

    long_id = "x" * 200
    assert len(sanitize_task_id(long_id)) <= 100


def test_worktree_slot_defaults():
    from superharness.engine.worktree_ops import WorktreeSlot

    slot = WorktreeSlot(index=0, branch="sh-t1-slot-0", worktree_path="/tmp/wt")
    assert slot.status == "pending"
    assert slot.project_dir == ""
    assert slot.cost_usd == 0.0


def test_private_aliases_still_importable():
    """parallel_dispatch must still export private aliases for backwards compat."""
    from superharness.engine.parallel_dispatch import (
        _sanitize_task_id,
        _create_worktree,
        _remove_worktree,
        _copy_superharness_state,
    )
    assert callable(_sanitize_task_id)
    assert callable(_create_worktree)
    assert callable(_remove_worktree)
    assert callable(_copy_superharness_state)


def test_swarm_imports_from_worktree_ops():
    """swarm.py should import WorktreeSlot from worktree_ops (not from parallel_dispatch)."""
    import importlib, inspect
    import superharness.engine.swarm as swarm_mod
    import superharness.engine.worktree_ops as wt_ops
    # The WorktreeSlot used in swarm should be the same class object as worktree_ops.WorktreeSlot
    assert swarm_mod.WorktreeSlot is wt_ops.WorktreeSlot
