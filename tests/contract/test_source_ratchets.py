"""Iteration 5 of PLAN-coding-practices.md — cheap counting guards that make
iterations 1 through 4 permanent.

Each ceiling below was measured fresh against the working tree at the time
this file was written (not copied from the plan, per its own recheck
instruction — the plan's numbers had already moved by the time iterations
1-4 landed). A ceiling may only go down in a future commit; if a change
needs to raise one, that is a deliberate, reviewable decision, not a silent
drift.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "superharness"

# Guards the PR #58 root cause: sys.exit() calls scattered through engine/
# instead of raising domain errors caught at the CLI boundary. Iteration 6
# migrated the 19 low-risk sites (contract.py, recall.py, validate.py,
# profile.py, operator.py, detect.py) behind engine/errors.py, whose
# handle_cli_error is the one legitimate remaining call — hence 88 - 19 + 1.
# Iteration 7 (not yet implemented) is expected to lower this to 1 by
# migrating discussion.py (38), inbox.py (23), and discuss.py (8).
_SYS_EXIT_IN_ENGINE_CEILING = 70

# Guards silently-swallowed errors (the "dead scanner" class of bug this
# audit's iteration 8, not yet implemented, narrows further). The audit doc
# (docs/AUDIT-coding-practices-2026-07-20.md) states 205 at authoring time;
# a fresh measurement against this working tree gives 728 via the same
# Path.rglob("*.py")-based counting this test itself uses (naive `grep -r`
# without --include="*.py" is not reliable here — it also matches stale
# bytecode under __pycache__, which produced a non-deterministic count
# while a concurrent test run was recompiling modules during this session).
# The 205 vs 728 gap predates iterations 1-4, which touched no `except
# Exception` clauses. Recheck instruction says to measure fresh, not trust
# the plan's copy — this is that fresh measurement.
_BROAD_EXCEPT_CEILING = 728

# Guards god-file growth. inbox_watch.py is already the largest file in the
# tree by a wide margin (out of scope to split — see docs/AUDIT-coding-practices-2026-07-20.md
# "What not to do"); this ceiling stops it, and everything else, from
# growing further unnoticed.
# 2026-07-21: bumped 4720->4721, the exact +1 line cost of fixing a real
# NameError crash bug (inbox_watch.py:2968, _ledger_record2 called without
# the local import 3 sibling call sites in this file already have). Ratchet
# did its job here — flagged the growth so it could be a deliberate,
# justified bump instead of silent creep.
_MAX_FILE_LINE_CEILING = 4721


def _count_matches(pattern: str, paths: list[Path]) -> int:
    regex = re.compile(pattern)
    total = 0
    for path in paths:
        total += len(regex.findall(path.read_text()))
    return total


def _all_src_files() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _engine_files() -> list[Path]:
    return sorted((SRC_ROOT / "engine").glob("*.py"))


def test_sys_exit_in_engine_does_not_grow():
    count = _count_matches(r"sys\.exit", _engine_files())
    assert count <= _SYS_EXIT_IN_ENGINE_CEILING, (
        f"sys.exit count in engine/ grew to {count} (ceiling "
        f"{_SYS_EXIT_IN_ENGINE_CEILING}). If this is a deliberate net-new "
        f"site, lower it by migrating an existing one first (see "
        f"PLAN-coding-practices.md iterations 6-7), or raise the ceiling "
        f"here as a reviewed, deliberate decision — never silently."
    )


def test_broad_except_does_not_grow():
    count = _count_matches(r"except Exception", _all_src_files())
    assert count <= _BROAD_EXCEPT_CEILING, (
        f"'except Exception' count grew to {count} (ceiling "
        f"{_BROAD_EXCEPT_CEILING}). See PLAN-coding-practices.md iteration 8 "
        f"for the narrowing policy; do not add a new broad catch without "
        f"logging exc_info=True at minimum."
    )


def test_no_file_exceeds_line_ceiling():
    """Per-file max, not a total — one file growing past the ceiling fails
    even if every other file shrank."""
    offenders = {}
    for path in _all_src_files():
        line_count = sum(1 for _ in path.open())
        if line_count > _MAX_FILE_LINE_CEILING:
            offenders[str(path.relative_to(REPO_ROOT))] = line_count
    assert not offenders, (
        f"file(s) exceeded the {_MAX_FILE_LINE_CEILING}-line ceiling: {offenders}"
    )


def _string_literal_value(node: ast.AST) -> str | None:
    """Best-effort extraction of a string literal's content, including the
    literal (non-interpolated) segments of an f-string. Returns None for
    anything that isn't a string constant or f-string (e.g. json.dumps(...),
    a variable, a format() call) — those can't be "generated Python source
    written as a string" in the sense this test guards against, since their
    content isn't visible as source text at all.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts)
    return None


def _generated_python_source_writes(path: Path) -> list[int]:
    """Line numbers of `.write_text(...)` calls whose argument is a string
    literal (or f-string) containing both "import " and "def " — the
    signature of a Python program embedded as a string, the exact shape of
    the daemon-monitor bug this plan's iteration 3 fixed."""
    tree = ast.parse(path.read_text(), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text" and node.args):
            continue
        text = _string_literal_value(node.args[0])
        if text is None:
            continue
        if "import " in text and "def " in text:
            offenders.append(node.lineno)
    return offenders


def test_no_python_source_generated_as_a_string():
    hits = {}
    for path in _all_src_files():
        offenders = _generated_python_source_writes(path)
        if offenders:
            hits[str(path.relative_to(REPO_ROOT))] = offenders
    assert not hits, (
        f"write_text() call(s) passing what looks like generated Python "
        f"source (a string literal containing both 'import ' and 'def '): "
        f"{hits}. This is the daemon-monitor-as-a-string shape iteration 3 "
        f"of PLAN-coding-practices.md removed — write real, importable "
        f"modules instead."
    )
