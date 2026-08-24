"""Contract: the typed handoff boundary has exactly one definition and one
write path.

`VALID_PHASES` must be defined once, in `handoffs_dao`, and re-exported (not
redefined) everywhere else it is used. Every raw `INSERT INTO handoffs` in
the codebase must go through `handoffs_dao.append` (the only place the typed
gate runs) except the legacy YAML importer, which is explicitly out of scope
(see docs/PLAN-typed-boundaries-context-hashing.md, "Out of scope").

See docs/PLAN-typed-boundaries-context-hashing.md, Iteration 1.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).parents[2] / "src" / "superharness"

_ALLOWED_RAW_INSERT_FILES = {
    _SRC / "engine" / "handoffs_dao.py",
    _SRC / "engine" / "migrate_yaml.py",
}


def test_valid_phases_single_definition() -> None:
    from superharness.engine import handoffs_dao
    from superharness.commands import handoff_write

    assert handoff_write.VALID_PHASES is handoffs_dao.VALID_PHASES


def test_no_raw_handoff_insert_outside_dao() -> None:
    offenders: list[str] = []
    for py_file in sorted(_SRC.rglob("*.py")):
        if py_file in _ALLOWED_RAW_INSERT_FILES:
            continue
        text = py_file.read_text(encoding="utf-8")
        if "INSERT INTO handoffs" in text:
            offenders.append(str(py_file.relative_to(_SRC.parent.parent)))
    assert offenders == [], (
        "Raw 'INSERT INTO handoffs' found outside handoffs_dao.py (bypasses "
        f"the typed boundary): {offenders}"
    )
