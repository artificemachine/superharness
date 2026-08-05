"""Iteration 1 of docs/CONCEPT-enforcement-parity.md — pin the pytest
configuration that makes an unregistered marker fail collection instead of
silently decorating a test with a marker nobody enforces.

Reads pyproject.toml as data; never executes pytest against a fixture repo.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


def _pytest_ini_options() -> dict:
    with PYPROJECT.open("rb") as f:
        data = tomllib.load(f)
    return data["tool"]["pytest"]["ini_options"]


def test_addopts_enables_strict_markers():
    """A typo'd @pytest.mark.* must fail collection, not pass silently.
    See docs/CONCEPT-enforcement-parity.md Iteration 1.

    The literal recipe from crossprose (`addopts = "-ra --strict-markers"`)
    does NOT actually enable enforcement under this repo's pytest (9.0.2):
    `--strict-markers` is implemented as `OverrideIniAction`, which appends
    to `namespace.override_ini`, but `Config.parse()`
    (_pytest/config/__init__.py) calls `determine_setup(override_ini=...)`
    using the *pre-addopts* argument-parse pass — before addopts (and any
    flag embedded in it) has even been read from the ini file. So a
    --strict-markers flag that only exists inside addopts never reaches the
    override mechanism; config.getini("strict_markers") silently stays
    None and unknown markers only warn. Verified empirically: a scratch
    file with @pytest.mark.netwrok passes with just a
    PytestUnknownMarkWarning when addopts is the only source of the flag,
    and only fails collection when --strict-markers is ALSO passed as a
    literal CLI argument (which redispatches the override before the ini
    is finalized). Since this repo's tooling (the pre-commit hook, CI, and
    any bare `pytest` invocation) never adds that CLI flag, the real,
    working knob is the native `strict_markers` boolean ini key — not the
    addopts CLI-flag alias. `addopts` is still asserted here for the `-ra`
    skip/xfail summary this iteration also wants; the marker-strictness
    assertion is on the ini key that actually works.
    """
    ini_options = _pytest_ini_options()
    addopts = ini_options.get("addopts", "")
    assert "-ra" in addopts.split(), (
        f"[tool.pytest.ini_options].addopts is {addopts!r} — missing -ra, "
        f"which prints the skip/xfail summary this suite currently hides."
    )
    assert ini_options.get("strict_markers") is True, (
        "[tool.pytest.ini_options].strict_markers is not `true` — this is "
        "the ini key that actually makes an unregistered marker fail "
        "collection (see this test's docstring for why `--strict-markers` "
        "inside addopts alone does not work on this pytest version)."
    )


def test_all_declared_markers_have_descriptions():
    """Every entry in markers = [...] must be 'name: description', not a
    bare name — a bare name registers the marker but documents nothing."""
    ini_options = _pytest_ini_options()
    markers = ini_options.get("markers", [])
    assert markers, "[tool.pytest.ini_options].markers is empty"
    undocumented = []
    for entry in markers:
        name, _, description = entry.partition(":")
        if not description.strip():
            undocumented.append(entry)
    assert not undocumented, (
        f"marker entries missing a ': description' suffix: {undocumented}"
    )
