"""Pin CHANGELOG.md's append-only property locally, at commit time.

CI enforces this via src/superharness/scripts/check-changelog-append-only.sh,
comparing the PR head against the PR base. That check is correct, but it is
the *only* place the property is verified, so the feedback loop is a full CI
round-trip.

That mattered on 2026-08-02. `.gitattributes` gives CHANGELOG.md a `union`
merge driver (PR #87), which resolves the conflict every parallel branch hits
there. Union keeps both sides — but it does not order them: merging main into
a branch put the branch's newer lines *before* main's, so main's content was
no longer a byte prefix and the guard failed. The union driver had turned a
loud conflict into a silent wrong answer, discovered only after a red CI job
and a force-push to correct it.

Dropping the union driver does not fix this. A hand-resolved conflict has the
same trap: the markers present "ours" before "theirs", and keeping both in
that order reproduces the exact failure. The gap is not the driver, it is
that nothing checked the property before push.

This test closes that. It lives in tests/contract/, which the pre-commit fast
subset runs, so a bad merge resolution fails in seconds instead of minutes.

Read-only: runs `git` plumbing that never writes, so it is compatible with the
autouse `_real_repo_untouched` hermeticity guard.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

# Refs to compare against, best first. A fork or a checkout whose remote is
# named something else still gets covered by the local branch.
UPSTREAM_CANDIDATES = ("origin/main", "main")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=False,
        check=False,
    )


def _resolve_base() -> str | None:
    """The merge base between HEAD and upstream main — the same commit CI
    uses as the PR base. Returns None when it cannot be determined (shallow
    clone, no upstream ref, tarball with no .git), in which case the test
    skips rather than inventing a comparison."""
    for ref in UPSTREAM_CANDIDATES:
        if (
            _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode
            != 0
        ):
            continue
        merge_base = _git("merge-base", "HEAD", ref)
        if merge_base.returncode == 0 and merge_base.stdout.strip():
            return merge_base.stdout.decode().strip()
    return None


def test_changelog_is_append_only_against_merge_base():
    """Everything the merge base had in CHANGELOG.md must still be a byte-exact
    prefix of the current file. New entries go at EOF; nothing above them may
    be edited, reordered, or removed.

    This is the property CI checks. Reproducing it here means a union-merge
    misordering, a rebase that interleaved entries, or an edit to a historical
    line is caught by the pre-commit hook rather than by a CI failure.
    """
    if _git("rev-parse", "--git-dir").returncode != 0:
        pytest.skip("not a git checkout — nothing to compare against")

    base = _resolve_base()
    if base is None:
        pytest.skip("no upstream main reachable (shallow clone or no remote)")

    show = _git("show", f"{base}:CHANGELOG.md")
    if show.returncode != 0:
        pytest.skip(f"CHANGELOG.md does not exist at merge base {base[:8]}")

    base_bytes = show.stdout
    current_bytes = CHANGELOG.read_bytes()

    if current_bytes.startswith(base_bytes):
        return

    # Report the first divergent line rather than dumping two large files.
    base_lines = base_bytes.split(b"\n")
    current_lines = current_bytes.split(b"\n")
    first_diff = next(
        (
            i
            for i, base_line in enumerate(base_lines)
            if i >= len(current_lines) or current_lines[i] != base_line
        ),
        min(len(base_lines), len(current_lines)),
    )
    expected = (
        base_lines[first_diff].decode(errors="replace")
        if first_diff < len(base_lines)
        else "<end of file>"
    )
    actual = (
        current_lines[first_diff].decode(errors="replace")
        if first_diff < len(current_lines)
        else "<end of file>"
    )

    raise AssertionError(
        f"CHANGELOG.md is no longer append-only against merge base {base[:8]}.\n"
        f"  First divergence at line {first_diff + 1}:\n"
        f"    merge base has: {expected[:160]}\n"
        f"    working tree has: {actual[:160]}\n"
        f"\n"
        f"  Most likely cause: a merge of main into this branch. CHANGELOG.md "
        f"has a `union` merge driver (.gitattributes), which keeps both sides "
        f"but does NOT order them — it puts this branch's lines before main's, "
        f"which breaks the byte-prefix rule CI enforces.\n"
        f"  Fix: rewrite CHANGELOG.md as the merge base's content verbatim, "
        f"then re-append this branch's own lines at EOF. Verify with:\n"
        f"    bash src/superharness/scripts/check-changelog-append-only.sh "
        f"--base-ref {base[:8]} --head-ref HEAD"
    )


def test_changelog_guard_can_actually_fail():
    """A guard that cannot fire is worse than none — it converts "nobody
    checked" into "something checked and it was fine". Proves the byte-prefix
    comparison rejects the exact shape a union misorder produces: the new line
    landing above the base content instead of at EOF."""
    base = b"# Changelog\n\n- 2026-01-01: first\n- 2026-01-02: second\n"

    appended = base + b"- 2026-01-03: third\n"
    assert appended.startswith(base), "a pure append must satisfy the prefix rule"

    # What union produces when merging main into a branch: the branch's line
    # is kept, but ahead of the base content it should follow.
    misordered = b"# Changelog\n\n- 2026-01-03: third\n- 2026-01-01: first\n- 2026-01-02: second\n"
    assert not misordered.startswith(base), (
        "the prefix check must reject a union misorder — if this passes, the "
        "guard above is blind to the exact bug it exists to catch"
    )

    edited = base.replace(b"first", b"FIRST") + b"- 2026-01-03: third\n"
    assert not edited.startswith(base), (
        "the prefix check must reject an edit to a historical line"
    )
