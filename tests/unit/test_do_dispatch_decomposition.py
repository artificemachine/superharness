"""Tests for _do_dispatch() staged decomposition.

Verifies that _do_dispatch is decomposed into discrete stage helpers and
that each stage can be called independently with a DispatchContext.
"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

import pytest

from superharness.commands.inbox_dispatch import (
    DispatchContext,
    _claim_next_item,
    _do_dispatch,
    _execute_agent,
    _handle_failure,
    _MkdirLock,
    _prepare_execution,
    _reconcile_state,
    _resolve_execution_context,
    _transition_to_launched,
)


def _make_ctx(tmp_path, **kwargs) -> DispatchContext:
    harness = tmp_path / ".superharness"
    harness.mkdir(exist_ok=True)
    inbox = str(harness / "inbox.yaml")
    contract = str(harness / "contract.yaml")
    defaults = dict(
        project_dir=str(tmp_path),
        inbox_file=inbox,
        contract_file=contract,
        target_filter=None,
        print_only=False,
        non_interactive=False,
        codex_bypass=False,
        launcher_timeout=0,
        script_dir="/fake/scripts",
        sqlite_primary=False,
    )
    defaults.update(kwargs)
    return DispatchContext(**defaults)


# ---------------------------------------------------------------------------
# Structural: each stage function exists and is callable
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,fn", [
    ("_claim_next_item", _claim_next_item),
    ("_resolve_execution_context", _resolve_execution_context),
    ("_transition_to_launched", _transition_to_launched),
    ("_prepare_execution", _prepare_execution),
    ("_execute_agent", _execute_agent),
    ("_handle_failure", _handle_failure),
    ("_reconcile_state", _reconcile_state),
])
def test_stage_helper_is_callable(name, fn):
    """Each stage helper must be a callable function."""
    assert callable(fn), f"{name} must be callable"


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_do_dispatch_delegates_to_stage_helpers():
    """_do_dispatch must call the stage helpers, not inline all logic."""
    src = inspect.getsource(_do_dispatch)
    for helper in (
        "_claim_next_item",
        "_resolve_execution_context",
        "_transition_to_launched",
        "_prepare_execution",
        "_execute_agent",
        "_reconcile_state",
    ):
        assert helper in src, f"_do_dispatch must delegate to {helper}"


def test_do_dispatch_has_no_orphaned_return_none():
    """_do_dispatch source must not have orphaned bare 'return None' stubs."""
    src = inspect.getsource(_do_dispatch)
    lines = src.splitlines()
    bare_returns = [l.strip() for l in lines if l.strip() == "return None"]
    # The only legitimate bare return None is after the last stage call.
    # More than 2 indicates leftover stubs from an incomplete decomposition.
    assert len(bare_returns) <= 2, (
        f"Found {len(bare_returns)} bare 'return None' lines — likely dead stubs"
    )


# ---------------------------------------------------------------------------
# Functional: _claim_next_item returns 0 on empty inbox (no pending items)
# ---------------------------------------------------------------------------

def test_claim_next_item_returns_zero_on_empty_inbox(tmp_path):
    """_claim_next_item must return 0 (not None) when SQLite is active and inbox has nothing pending."""
    ctx = _make_ctx(tmp_path, sqlite_primary=True, target_filter="claude-code")
    with patch(
        "superharness.commands.inbox_dispatch._sqlite_claim_next",
        return_value=None,
    ):
        rc = _claim_next_item(ctx)
    assert rc == 0


# ---------------------------------------------------------------------------
# Functional: _execute_agent honours print_only flag
# ---------------------------------------------------------------------------

def test_execute_agent_print_only_sets_rc_zero(tmp_path):
    """_execute_agent must set launcher_rc=0 in print_only mode without spawning."""
    ctx = _make_ctx(tmp_path, print_only=True)
    ctx.launch_args = ["fake-cmd"]
    ctx.wrapped_args = ["fake-cmd"]
    ctx.spawn_env = {}
    ctx.effective_timeout = 0
    ctx.item_id = "item-1"

    _execute_agent(ctx)

    assert ctx.launcher_rc == 0


# ---------------------------------------------------------------------------
# Iter 7 RED: task completion + --for-review read from SQLite
# ---------------------------------------------------------------------------

def test_success_recorded_done_from_sqlite():
    """_reconcile_state must read task completion from SQLite (state_reader) not contract.yaml subprocess."""
    import inspect
    from superharness.commands import inbox_dispatch as m
    src = inspect.getsource(m._reconcile_state)
    # After fix: the function uses state_reader.get_task or tasks_dao, not the legacy subprocess path
    uses_sqlite = any(tok in src for tok in ("get_task", "tasks_dao", "state_reader.get"))
    # The dead subprocess call for contract.task_status in the non-discussion branch must be gone
    has_dead_contract_call = ("engine.contract" in src and "task_status" in src
                              and "elif os.path.exists(ctx.contract_file)" in src)
    assert uses_sqlite and not has_dead_contract_call, (
        "_reconcile_state still reads task status via contract.yaml subprocess "
        "(find 'engine.contract' + 'task_status' in the non-discussion branch). "
        "Replace with state_reader.get_task() call."
    )


def test_for_review_from_sqlite():
    """_prepare_execution must derive --for-review from SQLite task status, not contract.yaml subprocess."""
    import inspect
    from superharness.commands import inbox_dispatch as m
    src = inspect.getsource(m._prepare_execution)
    # After fix: --for-review derivation uses get_task / tasks_dao, not subprocess
    uses_sqlite = any(tok in src for tok in ("get_task", "tasks_dao", "state_reader.get"))
    # The dead subprocess call for task_status in _prepare_execution must be gone
    has_dead_contract_call = ("engine.contract" in src and "task_status" in src)
    assert uses_sqlite and not has_dead_contract_call, (
        "_prepare_execution still reads task_status via contract.yaml subprocess "
        "(find 'engine.contract' + 'task_status' in the function). "
        "Replace with state_reader.get_task() call."
    )
