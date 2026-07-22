"""Guard: no module under src/superharness/ may define the same top-level
function name twice.

Regression test for `engine/profile.py` carrying two `def write_field(...)`
at module scope — the first (naive, non-atomic write) was 100% dead code,
silently shadowed by the second (atomic tmp-file-then-rename write) since
Python executes top-level defs in order and the last one wins. Any reader
who stopped at the first definition believed writes weren't atomic; they
were, two definitions later, for reasons unrelated to reading order. `ruff
--select F811` catches this but isn't run as a blocking CI gate on every
push, so this guard makes it a hard test failure instead of an optional lint
finding. Found by /gauntlet Stage 3 (code_quality), 2026-07-22.

Only checks top-level (module-scope) function/class defs — nested defs
(closures, decorated overloads inside a class) are legitimately allowed to
repeat a name across different scopes and are out of scope for this check.
"""
from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src" / "superharness"


def _duplicate_top_level_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    seen: dict[str, int] = {}
    dupes: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if name in seen:
                dupes.append(f"{name} (first at line {seen[name]}, redefined at line {node.lineno})")
            else:
                seen[name] = node.lineno
    return dupes


def test_no_duplicate_top_level_function_defs():
    offenders: list[str] = []
    for py_file in sorted(_SRC.rglob("*.py")):
        dupes = _duplicate_top_level_names(py_file)
        if dupes:
            rel = py_file.relative_to(_SRC.parent.parent)
            offenders.extend(f"{rel}: {d}" for d in dupes)
    if offenders:
        import pytest

        pytest.fail(
            "Module-scope function redefined (the earlier definition is dead code, "
            "silently shadowed — see docstring for the profile.py incident this guards):\n"
            + "\n".join(f"  {o}" for o in offenders)
        )
