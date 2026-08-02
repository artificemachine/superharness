"""Iteration 2 of docs/CONCEPT-enforcement-parity.md — pin the enforcement
commands in CI, the pre-commit hook, and the two duplicated hook
directories, so a silent de-fanging (the branch-guard disease; see
docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md) cannot recur
unnoticed.

Pattern note: the form (yaml.safe_load a workflow, join step `run:`
strings, assert substrings) comes from the crossprose project's
`tests/unit/test_ci_parity.py` — a separate repository, read for form
only. Nothing here depends on it.

Everything here reads files as data. Nothing is executed, no hook is
invoked, no agent is spawned, no `.superharness/` state is touched.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PRECOMMIT_HOOK = REPO_ROOT / ".project-hooks" / "pre-commit"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
PYPROJECT = REPO_ROOT / "pyproject.toml"

HOOKS_DIR_ROOT = REPO_ROOT / "adapters" / "claude-code" / "hooks"
HOOKS_DIR_SRC = REPO_ROOT / "src" / "superharness" / "adapters" / "claude-code" / "hooks"

# ---------------------------------------------------------------------------
# Known, already-real divergence between the two hook copies.
#
# Measured fresh against this worktree on 2026-08-01 (not assumed from the
# plan, which only asserted the two dirs "must stay byte-identical" per PR
# #87's commit message — that sentence is unenforced and, per this
# measurement, already false for 5 of 9 files). This is a real bug this
# iteration surfaced, not fixed: the hard constraints for this task forbid
# editing any hook file. Each entry below is the exact reason the pair
# differs today; closing an entry (making the pair byte-identical again) is
# separate follow-up work, not this iteration's job. This allowlist may
# only shrink.
# ---------------------------------------------------------------------------
KNOWN_DIVERGENT_HOOK_FILES = {
    # Root copy still wires the Stop-hook slot to session-stop.sh; the src
    # copy wires the same slot to session-turn-end.sh. This is a live
    # consequence of the session-stop.sh split below, not a formatting
    # nit — the packaged (src) hook set and the repo-root hook set fire
    # different scripts for the same event.
    "hooks.json": (
        "root wires Stop -> session-stop.sh, src wires Stop -> "
        "session-turn-end.sh (see session-stop.sh entry)."
    ),
    # src copy carries a *.env.example carve-out (scope-guard must not
    # block edits to the checked-in template) that the root copy lacks.
    "scope-guard.sh": (
        "src copy excludes *.env.example from the sensitive-file block; "
        "root copy still blocks edits to it."
    ),
    # src copy was migrated off contract.yaml onto
    # superharness.engine.state_reader / state.sqlite3; the root copy still
    # parses .superharness/contract.yaml directly with a regex/PyYAML,
    # which is dead per this repo's "State lives in SQLite" rule.
    "session-start.sh": (
        "root copy still reads .superharness/contract.yaml directly; src "
        "copy reads via engine.state_reader against state.sqlite3 (root "
        "predates the SQLite-source-of-truth migration)."
    ),
    # src copy is explicitly marked DEPRECATED in its own header ("do not
    # register as a Stop hook... superseded by session-turn-end.sh +
    # session-exit.sh"); the root copy has no such header and is still the
    # full, active legacy implementation reading contract.yaml.
    "session-stop.sh": (
        "src copy is header-marked DEPRECATED (superseded by the "
        "session-turn-end.sh + session-exit.sh split); root copy is the "
        "old, still-active implementation with no deprecation notice."
    ),
    # src copy is the live half of the split described above and contains
    # an extra pending-discussion-prompt surfacing block the root copy
    # lacks entirely.
    "session-turn-end.sh": (
        "src copy has an extra 'surface pending discussion prompts' block "
        "(reads $SH_DIR/discussions/*/round-*.prompt.md) the root copy "
        "does not have."
    ),
}


def _repo_root() -> Path:
    return REPO_ROOT


def _hook_text() -> str:
    return PRECOMMIT_HOOK.read_text()


def _ci_workflow() -> dict:
    with CI_WORKFLOW.open() as f:
        return yaml.safe_load(f)


def _ci_unit_run_text() -> str:
    """Every `run:` step's text in the tests.yml `unit-tests` job, joined —
    covers both the Linux/macOS and Windows step variants."""
    workflow = _ci_workflow()
    job = workflow["jobs"]["unit-tests"]
    return "\n".join(step.get("run", "") for step in job["steps"])


def _pyproject_fail_under() -> int:
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    return data["tool"]["coverage"]["report"]["fail_under"]


def _precommit_branches() -> tuple[str, str]:
    """(then_block, else_block) of the hook's
    `if [[ SUPERHARNESS_FULL_PRECOMMIT ]]; then ... else ... fi` — structural
    extraction so checks land on the real invocation lines, not on a
    comment elsewhere in the file that happens to share the same words."""
    text = _hook_text()
    match = re.search(
        r"if\s*\[\[.*?\]\];\s*then\n(.*?)\nelse\n(.*?)\nfi\b", text, re.DOTALL
    )
    assert match, f"{PRECOMMIT_HOOK}: could not locate the if/then/else/fi structure"
    return match.group(1), match.group(2)


def test_precommit_unsets_git_plumbing_env():
    """Regression pin for the 2026-07-31 incident: the hook must unset the
    GIT_* plumbing env vars before running the suite, or a caller's
    exported GIT_DIR/GIT_INDEX_FILE silently redirects the fixture suite
    onto the real repository. See
    docs/bugs/BUG-2026-07-31-test-suite-git-dir-escape.md."""
    text = _hook_text()
    assert "unset GIT_DIR" in text, (
        f"{PRECOMMIT_HOOK}: missing 'unset GIT_DIR' — the 2026-07-31 "
        f"git-dir escape guard is gone."
    )
    assert "GIT_INDEX_FILE" in text, (
        f"{PRECOMMIT_HOOK}: missing 'GIT_INDEX_FILE' in the unset list."
    )


def test_precommit_deselects_network_tests():
    """`-m "not network"` must appear in both the fast subset and the
    SUPERHARNESS_FULL_PRECOMMIT=1 full-suite branch — provider-dependent
    tests must never be able to block a commit.

    Checks the two `if`/`else` blocks structurally rather than counting
    substring occurrences across the whole file: a mutation check caught
    that a naive `text.count(...) >= 2` assertion is blind to deleting one
    real branch's flag, because an unrelated comment line
    ("`-m \"not network\"` keeps provider-dependent tests...") holds the
    count at 2 anyway — the exact "looks-enforced-but-isn't" shape this
    whole iteration exists to catch.
    """
    then_block, else_block = _precommit_branches()
    assert '-m "not network"' in then_block, (
        f"{PRECOMMIT_HOOK}: SUPERHARNESS_FULL_PRECOMMIT=1 branch is missing "
        f'-m "not network".'
    )
    assert '-m "not network"' in else_block, (
        f"{PRECOMMIT_HOOK}: fast-subset branch is missing "
        f'-m "not network".'
    )


def test_precommit_subset_includes_git_env_guard():
    """The fast subset must run tests/unit/test_git_env_isolation.py — the
    one unit test file allowed to skip the tests/unit/ bulk exclusion,
    because it's the regression test for the escape this hook itself
    guards against."""
    text = _hook_text()
    assert "tests/unit/test_git_env_isolation.py" in text, (
        f"{PRECOMMIT_HOOK}: fast subset no longer names "
        f"tests/unit/test_git_env_isolation.py."
    )
    guard_test = REPO_ROOT / "tests" / "unit" / "test_git_env_isolation.py"
    assert guard_test.is_file(), f"{guard_test} does not exist"


def test_ci_unit_job_runs_full_unit_suite():
    """CI's unit-tests job must run the full tests/unit suite — it must not
    inherit the pre-commit hook's fast subset, or a real regression could
    pass the hook and then pass CI too."""
    run_text = _ci_unit_run_text()
    assert "pytest tests/unit" in run_text, (
        f".github/workflows/tests.yml unit-tests job run text does not "
        f"contain 'pytest tests/unit': {run_text!r}"
    )


def test_ci_coverage_floor_matches_pyproject():
    """The --cov-fail-under value in CI's unit-tests job must equal
    [tool.coverage.report].fail_under in pyproject.toml — pinning the
    *equality*, not the number, so the two can never silently drift apart
    (a local `pytest --cov` run and CI must enforce the same floor)."""
    run_text = _ci_unit_run_text()
    matches = [int(m) for m in re.findall(r"--cov-fail-under=(\d+)", run_text)]
    assert matches, (
        f".github/workflows/tests.yml unit-tests job has no "
        f"--cov-fail-under= flag: {run_text!r}"
    )
    pyproject_floor = _pyproject_fail_under()
    mismatched = [m for m in matches if m != pyproject_floor]
    assert not mismatched, (
        f"--cov-fail-under value(s) {matches} in the unit-tests job do not "
        f"all equal pyproject.toml's fail_under={pyproject_floor}."
    )


def test_hook_copies_are_byte_identical():
    """Every file in adapters/claude-code/hooks/ must be byte-identical to
    its namesake in src/superharness/adapters/claude-code/hooks/, and vice
    versa (checked both directions, so a file added to only one side also
    fails) — except the files in KNOWN_DIVERGENT_HOOK_FILES, a real,
    already-existing gap this iteration surfaces but does not fix (hook
    files are out of scope for this task). That allowlist may only
    shrink."""
    root_names = {p.name for p in HOOKS_DIR_ROOT.iterdir() if p.is_file()}
    src_names = {p.name for p in HOOKS_DIR_SRC.iterdir() if p.is_file()}
    only_root = root_names - src_names
    only_src = src_names - root_names
    assert not only_root, f"file(s) only in {HOOKS_DIR_ROOT}: {sorted(only_root)}"
    assert not only_src, f"file(s) only in {HOOKS_DIR_SRC}: {sorted(only_src)}"

    mismatched = {}
    for name in sorted(root_names & src_names):
        if name in KNOWN_DIVERGENT_HOOK_FILES:
            continue
        root_bytes = (HOOKS_DIR_ROOT / name).read_bytes()
        src_bytes = (HOOKS_DIR_SRC / name).read_bytes()
        if root_bytes != src_bytes:
            mismatched[name] = f"{HOOKS_DIR_ROOT / name} != {HOOKS_DIR_SRC / name}"
    assert not mismatched, (
        f"hook copy(ies) diverged outside KNOWN_DIVERGENT_HOOK_FILES: "
        f"{mismatched}. Either this is new drift (fix it) or a real, "
        f"deliberate change (add it to KNOWN_DIVERGENT_HOOK_FILES with a "
        f"reason)."
    )


def test_subset_paths_exist():
    """Every tests/... path named in the pre-commit hook's fast-subset
    invocation must exist on disk — a renamed/deleted directory would
    otherwise turn the hook into a silent no-op that still exits 0."""
    _then_block, else_block = _precommit_branches()
    paths = re.findall(r"tests/\S+", else_block)
    assert paths, f"{PRECOMMIT_HOOK}: no tests/... paths found in the else branch"
    missing = [p for p in paths if not (REPO_ROOT / p).exists()]
    assert not missing, f"path(s) named in the hook do not exist on disk: {missing}"
