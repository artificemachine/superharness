"""docs/README.md link guard.

Emitted by /bulletproof (2026-07-22) after a follow-up audit found docs/README.md
— fixed one week earlier by a docs-decluster pass — still had 12 dead links to
files that were never git-tracked at all (gitignored working-notes docs like
docs/PLAN-mvf.md, docs/bulletproof-report-2026-06-08.md), plus a 13th dead link
(docs/PYPI_SETUP.md) the prior fix pass never checked. The prior pass verified
only the specific 18 files it had just untracked — it never re-scanned the full
index against everything actually missing from git. This guard makes "the docs
index has zero broken links" a computed fact instead of a point-in-time claim.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO = Path(__file__).parents[1]
_INDEX = _REPO / "docs" / "README.md"

_LINK = re.compile(r"\]\(([^)]+\.md)\)")


def _tracked_basenames() -> set[str]:
    out = subprocess.run(
        ["git", "ls-files", "docs/"], capture_output=True, text=True, cwd=_REPO, check=True
    ).stdout
    return {line.split("/")[-1] for line in out.splitlines() if line}


def test_docs_readme_links_resolve():
    """Every relative .md link in docs/README.md must point to a git-tracked file."""
    if not _INDEX.is_file():
        return
    tracked = _tracked_basenames()
    dead: list[str] = []
    for lineno, line in enumerate(_INDEX.read_text(encoding="utf-8").splitlines(), 1):
        for target in _LINK.findall(line):
            if target.startswith("http") or target.startswith(".."):
                continue
            base = target.split("/")[-1]
            if base not in tracked:
                dead.append(f"docs/README.md:{lineno}  -> {target}")
    if dead:
        import pytest

        pytest.fail(
            "docs/README.md links to files that are not git-tracked "
            "(broken for anyone who clones the repo):\n"
            + "\n".join(f"  {d}" for d in dead)
        )
