"""Peer-reviewer candidate selection — defect 3 of
``docs/bugs/BUG-2026-09-18-inbox-watch-reviewer-tier-gate.md``.

`_auto_close_report_ready` hardcoded
``["claude-code", "codex-cli", "gemini-cli", "opencode"]`` as its reviewer
candidate list. When `pi` was registered as a harness that literal silently
excluded it, so a `pi`-owned task could never receive an autonomous peer reviewer
— the cross-pollination guard removed the owner, leaving an empty list.

The candidate list now comes from the harness registry. Because `KNOWN_HARNESSES`
is sorted and `pi` sorts last, the first candidate (which is the one the live path
picks) is unchanged for every owner except `pi`, which previously got none — so
this is a behaviour-preserving fix for the case that worked and a repair for the
case that did not.

Deliberately out of scope: the model-tier half of the gate. See defects 1 and 2 in
the same report.
"""

from __future__ import annotations

import inspect

from superharness.commands import inbox_watch
from superharness.commands.inbox_watch import _peer_reviewer_candidates
from superharness.harnesses import KNOWN_HARNESSES


def test_candidates_never_include_the_owner():
    """Cross-pollination: an owner may not review its own task."""
    for owner in KNOWN_HARNESSES:
        assert owner not in _peer_reviewer_candidates(owner)


def test_candidates_are_the_registry_minus_the_owner():
    for owner in KNOWN_HARNESSES:
        expected = [harness for harness in KNOWN_HARNESSES if harness != owner]
        assert _peer_reviewer_candidates(owner) == expected


def test_a_pi_owner_gets_a_candidate():
    """This is the defect: `pi` owned a task and got an empty candidate list."""
    assert _peer_reviewer_candidates("pi"), "a pi-owned task would get no reviewer"


def test_pi_is_a_candidate_for_other_owners():
    assert "pi" in _peer_reviewer_candidates("claude-code")


def test_an_unknown_owner_still_gets_the_full_registry():
    assert _peer_reviewer_candidates("some-other-agent") == list(KNOWN_HARNESSES)


def test_candidates_follow_the_registry_without_editing_inbox_watch(monkeypatch):
    """A later registration must be picked up automatically.

    This is the property the hardcoded literal broke: the list had to be edited by
    hand in two places, and was only edited in one.
    """
    monkeypatch.setattr("superharness.harnesses.KNOWN_HARNESSES", ["alpha", "beta"])

    assert _peer_reviewer_candidates("alpha") == ["beta"]


def test_auto_close_uses_the_registry_and_not_a_literal():
    """Wiring guard: the live path must call the helper, not rebuild the list.

    The helper's own tests cannot catch a caller that ignores it — which is exactly
    how the drift survived, since `_cancel_undispatchable_agents` in the same file
    already used the registry correctly.
    """
    source = inspect.getsource(inbox_watch._auto_close_report_ready)

    assert "_peer_reviewer_candidates(" in source
    for stale_literal in (
        '"claude-code", "codex-cli"',
        "'claude-code', 'codex-cli'",
        "known_agents = [",
    ):
        assert stale_literal not in source, (
            f"the live auto-review path still builds a harness list by hand: "
            f"{stale_literal!r}"
        )
