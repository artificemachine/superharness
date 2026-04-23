"""Guard-table collapse regression tests.

These tests encode the acceptance criteria for
chore.collapse-guards-next-action:

  - delegate._DISC_ROUND_RE is the same object as engine.next_action._DISC_ROUND_RE
    (no local duplicate in delegate.py)
  - contract_today has no local _DISC_ROUND_RE or _infer_workflow
    (both must come from engine.next_action)
  - All existing accept/reject cases for _is_delegate_candidate are unchanged.

RED → fails before the refactor; GREEN → passes after.
"""
from __future__ import annotations

import inspect


# ---------------------------------------------------------------------------
# Single-source-of-truth structural tests
# ---------------------------------------------------------------------------

def test_delegate_disc_round_re_not_defined_locally():
    """delegate.py must not define its own _DISC_ROUND_RE via re.compile.

    The canonical regex lives in engine.next_action; delegate must import it,
    not redefine it.  We check the source text rather than object identity
    because Python's regex LRU cache makes identical patterns share the same
    compiled object regardless of where they were compiled.
    """
    import superharness.commands.delegate as delegate_mod

    src = inspect.getsource(delegate_mod)
    assert "_DISC_ROUND_RE = re.compile" not in src, (
        "delegate.py defines a local _DISC_ROUND_RE — remove it and import "
        "from engine.next_action instead"
    )


def test_contract_today_has_no_local_disc_round_re():
    """contract_today must not define its own _DISC_ROUND_RE via re.compile."""
    import superharness.commands.contract_today as ct_mod

    src = inspect.getsource(ct_mod)
    assert "_DISC_ROUND_RE = re.compile" not in src, (
        "contract_today still defines a local _DISC_ROUND_RE — remove it"
    )


def test_contract_today_has_no_local_infer_workflow():
    """contract_today must not define its own _infer_workflow function."""
    import superharness.commands.contract_today as ct_mod

    src = inspect.getsource(ct_mod)
    assert "def _infer_workflow" not in src, (
        "contract_today still defines a local _infer_workflow — remove it"
    )


# ---------------------------------------------------------------------------
# Behaviour-unchanged tests for _is_delegate_candidate
# ---------------------------------------------------------------------------

def test_is_delegate_candidate_impl_plan_approved():
    from superharness.commands.contract_today import _is_delegate_candidate
    assert _is_delegate_candidate({"id": "feat.x", "status": "plan_approved", "workflow": "implementation"})


def test_is_delegate_candidate_impl_in_progress():
    from superharness.commands.contract_today import _is_delegate_candidate
    assert _is_delegate_candidate({"id": "feat.x", "status": "in_progress", "workflow": "implementation"})


def test_is_delegate_candidate_impl_todo_is_false():
    from superharness.commands.contract_today import _is_delegate_candidate
    assert not _is_delegate_candidate({"id": "feat.x", "status": "todo", "workflow": "implementation"})


def test_is_delegate_candidate_quick_todo():
    from superharness.commands.contract_today import _is_delegate_candidate
    assert _is_delegate_candidate({"id": "chore.x", "status": "todo", "workflow": "quick"})


def test_is_delegate_candidate_note_todo():
    from superharness.commands.contract_today import _is_delegate_candidate
    assert _is_delegate_candidate({"id": "note.x", "status": "todo", "workflow": "note"})


def test_is_delegate_candidate_discussion_todo_is_false():
    """Discussion-round tasks with status=todo are not dispatchable."""
    from superharness.commands.contract_today import _is_delegate_candidate
    assert not _is_delegate_candidate({"id": "discuss-abc/round-1", "status": "todo"})


def test_is_delegate_candidate_discussion_always_false():
    """Discussion-round tasks are never delegate candidates via contract_today.

    Discussion dispatch goes through a separate path; _is_delegate_candidate
    returns False for all statuses of the discussion workflow.
    """
    from superharness.commands.contract_today import _is_delegate_candidate
    assert not _is_delegate_candidate({"id": "discuss-abc/round-1", "status": "in_progress"})
    assert not _is_delegate_candidate({"id": "discuss-abc/round-1", "status": "todo"})


def test_is_delegate_candidate_workflow_inferred_from_id_pattern():
    """When no workflow field is set, discussion-round id pattern drives inference."""
    from superharness.commands.contract_today import _is_delegate_candidate
    # No explicit workflow field — must be inferred via next_action.infer_workflow
    assert not _is_delegate_candidate({"id": "discuss-topic/round-5", "status": "plan_approved"})
