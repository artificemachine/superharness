"""Doc-drift guard — keeps doctrine honest about the code it describes.

Emitted by /bulletproof (v13, 2026-05-29) after a general audit found that the
code invariants were all guard-enforced, but several DOCS had drifted: they
named deleted modules and described a pre-SQLite source of truth. Code claims
had CI guards and stayed fixed; doc claims had none and rotted between audits.
This guard closes that asymmetry.

Extended by /bulletproof (2026-07-22) after a follow-up audit found docs/GUIDE.md
was not in _DOCTRINE at all, and the SoT check only caught literal "X is the
source of truth" phrasing — it missed GUIDE.md describing contract.yaml/inbox.yaml
as an operational read/write path ("read contract.yaml + handoffs", "write
subtasks to contract.yaml") without ever using the words "source of truth".
GUIDE.md is the project's primary command reference (see feedback memory
feedback_ship_doc_sync.md) and had drifted in 8 places for 6+ weeks undetected.

Project facts live HERE (deny-list, doctrine paths), not in the global command.

Checks:
  1. Named-entity existence — every *.py file named in doctrine resolves on disk.
  2. SoT consistency — no doctrine file calls a state-YAML the "source of truth"
     (AGENTS.md/CLAUDE.md establish SQLite as the source of truth).
  3. Operational-claim consistency — no doctrine file describes reading, writing,
     creating, recording, or enqueuing to a state-YAML as if it were live state
     (AGENTS.md/CLAUDE.md establish these as export-only artifacts).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).parents[1]

# --- project facts (this repo's doctrine) -------------------------------------

_DOCTRINE = [
    "AGENTS.md",
    "CLAUDE.md",
    "docs/ARCHITECTURE.md",
    "docs/GUIDE.md",
]

# State YAMLs whose source-of-truth is SQLite (must never be called the SoT).
_STATE_YAMLS = ("contract.yaml", "inbox.yaml", "decisions.yaml", "failures.yaml")

# A state-YAML within ~40 chars of "source of truth" is a stale storage-SoT claim.
_STALE_SOT = re.compile(
    r"(" + "|".join(re.escape(y) for y in _STATE_YAMLS) + r")[^\n]{0,40}source of truth",
    re.IGNORECASE,
)

# Negation tokens that make a "source of truth" mention CORRECT (e.g. "no longer
# the source of truth", "DEAD", "tombstone"). A line with any of these is fine.
_NEGATION = re.compile(
    r"\b(no longer|not|never|n't|dead|tombstone|legacy|deprecated|was|former|export artifact)\b",
    re.IGNORECASE,
)

# Verbs that treat a state-YAML as a live, operational read/write target rather
# than an export/tombstone artifact. Ordered to match "<verb> ... <state-yaml>"
# (the phrasing every real GUIDE.md violation used: "read contract.yaml",
# "write subtasks to contract.yaml", "Creates a first task in contract.yaml").
_STATE_OP_VERBS = r"(?:reads?|writes?|written|creates?|records?|recording|append(?:s|ed)?|enqueues?)"
_STALE_STATE_OP = re.compile(
    r"\b" + _STATE_OP_VERBS + r"\b[^\n]{0,60}(?:"
    + "|".join(re.escape(y) for y in _STATE_YAMLS)
    + r")(?!\.lock)",
    re.IGNORECASE,
)

# *.py references in doctrine: backtick-quoted or file-tree style.
# Hyphens are part of filenames (dashboard-ui.py); glob patterns (*_dao.py) are skipped.
_PY_REF = re.compile(r"`?([A-Za-z0-9_./*-]+\.py)`?")

# Search roots for resolving a named module by basename.
_SEARCH_ROOTS = [_REPO / "src", _REPO / "tests"]


def _doctrine_files() -> list[Path]:
    return [_REPO / d for d in _DOCTRINE if (_REPO / d).is_file()]


def _resolves(ref: str) -> bool:
    """True if a doctrine-named *.py reference resolves to a real file."""
    # exact path from repo root or from src/superharness
    for base in (_REPO, _REPO / "src" / "superharness"):
        if (base / ref).is_file():
            return True
    # basename anywhere under src/ or tests/
    name = Path(ref).name
    for root in _SEARCH_ROOTS:
        if root.is_dir() and any(root.rglob(name)):
            return True
    return False


class TestDocDrift:
    def test_named_modules_exist(self):
        """Every *.py file named in doctrine must resolve on disk."""
        missing: list[str] = []
        for doc in _doctrine_files():
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                for ref in _PY_REF.findall(line):
                    if not ref.endswith(".py"):
                        continue
                    if "*" in ref:  # glob pattern (e.g. *_dao.py), not a literal file
                        continue
                    if not _resolves(ref):
                        missing.append(f"{doc.relative_to(_REPO)}:{lineno}  names '{ref}' (no such file)")
        if missing:
            pytest.fail(
                "Doctrine names *.py files that do not exist (delete-the-file-keep-the-doc drift):\n"
                + "\n".join(f"  {m}" for m in sorted(set(missing)))
            )

    def test_no_state_yaml_called_source_of_truth(self):
        """No doctrine file may call a state-YAML the source of truth (SQLite is)."""
        hits: list[str] = []
        for doc in _doctrine_files():
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                if _STALE_SOT.search(line) and not _NEGATION.search(line):
                    hits.append(f"{doc.relative_to(_REPO)}:{lineno}  {line.strip()}")
        if hits:
            pytest.fail(
                "Doctrine calls a state-YAML the source of truth — SQLite is the SoT.\n"
                "Fix the doc (or add a legacy/superseded banner):\n"
                + "\n".join(f"  {h}" for h in hits)
            )

    def test_no_state_yaml_described_as_operational(self):
        """No doctrine file may describe reading/writing/creating a state-YAML
        as if it were live state — these are export-only artifacts (SQLite is
        the read/write path). Catches operational phrasing that doesn't use the
        words "source of truth" (e.g. "read contract.yaml + handoffs")."""
        hits: list[str] = []
        for doc in _doctrine_files():
            for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
                if _STALE_STATE_OP.search(line) and not _NEGATION.search(line):
                    hits.append(f"{doc.relative_to(_REPO)}:{lineno}  {line.strip()}")
        if hits:
            pytest.fail(
                "Doctrine describes reading/writing a state-YAML as live state — "
                "SQLite (state.db) is the read/write path; state-YAMLs are export-only.\n"
                "Fix the doc (or add a legacy/superseded banner, or an 'export artifact' note):\n"
                + "\n".join(f"  {h}" for h in hits)
            )
