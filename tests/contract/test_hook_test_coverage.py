"""Iteration 3 of docs/CONCEPT-enforcement-parity.md — every adapter hook
must map to a test file, or be named in an explicit, shrinking allowlist.
An untested guard is the most dangerous kind: see
docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md for the incident
this whole plan responds to, and tests/contract/test_source_ratchets.py
for the in-repo ratchet precedent this file matches in style.

Pattern note: the completeness-sweep form comes from the crossprose
project's `tests/unit/test_recipes_complete.py` — a separate repository,
read for form only. Nothing here depends on it.

Reads the hooks directory and tests/unit/ as data only.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "adapters" / "claude-code" / "hooks"
UNIT_TESTS_DIR = REPO_ROOT / "tests" / "unit"

# ---------------------------------------------------------------------------
# Measured fresh against this worktree on 2026-08-01 (not copied from the
# plan's prediction, per its own recheck instruction — the plan predicted
# {ledger-append.sh, session-exit.sh, session-start.sh, session-turn-end.sh}
# untested; reality is smaller: tests/unit/test_ledger_append.py and
# tests/unit/test_session_start.py already exist. Both remaining gaps were
# closed 2026-08-03 by tests/unit/test_session_exit.py and
# tests/unit/test_session_turn_end.py as part of issue #92's
# definition-of-done #4. This allowlist may only shrink — closing an
# entry means writing the test, not deleting the line.
# ---------------------------------------------------------------------------
KNOWN_UNTESTED: dict[str, str] = {}


def _hook_files() -> list[Path]:
    """Executable hook sources — *.sh and *.py only. hooks.json is config,
    not executable, and is excluded by this pattern deliberately."""
    return sorted(
        p for p in HOOKS_DIR.iterdir()
        if p.is_file() and p.suffix in (".sh", ".py")
    )


def _candidate_test_path(hook_name: str) -> Path:
    """tests/unit/test_<hook-stem-with-underscores>.py — e.g.
    branch-guard.sh -> tests/unit/test_branch_guard.py. branch_guard.py
    resolves to the same candidate name, which is fine: either source file
    landing a hit satisfies the sweep."""
    stem = Path(hook_name).stem.replace("-", "_")
    return UNIT_TESTS_DIR / f"test_{stem}.py"


def test_every_hook_has_a_test_or_allowlist_entry():
    gaps = {}
    for hook_path in _hook_files():
        name = hook_path.name
        if name in KNOWN_UNTESTED:
            continue
        candidate = _candidate_test_path(name)
        if not candidate.is_file():
            gaps[name] = str(candidate)
    assert not gaps, (
        f"hook(s) with no matching test and no allowlist entry: {gaps}. "
        f"Write the test, or add the hook to KNOWN_UNTESTED with a "
        f"justification comment — see "
        f"docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md for why "
        f"untested guards are the most dangerous kind."
    )


def test_allowlist_entries_are_still_untested():
    """The ratchet's other jaw: once someone writes
    tests/unit/test_session_exit.py (or _turn_end), this test fails and
    forces the allowlist entry to be deleted — a stale allowlist entry
    can't silently linger once it's no longer true."""
    now_tested = [
        name for name in KNOWN_UNTESTED
        if _candidate_test_path(name).is_file()
    ]
    assert not now_tested, (
        f"KNOWN_UNTESTED entries that now have a test file and must be "
        f"removed from the allowlist: {now_tested}"
    )


def test_allowlist_names_real_hooks():
    """A deleted hook can't haunt the allowlist forever."""
    real_hook_names = {p.name for p in _hook_files()}
    stale = set(KNOWN_UNTESTED) - real_hook_names
    assert not stale, (
        f"KNOWN_UNTESTED name(s) that no longer exist in {HOOKS_DIR}: "
        f"{stale}"
    )
