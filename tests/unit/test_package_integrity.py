"""Package integrity invariants.

Prevents the class of bugs where:
- pyproject.toml version is bumped but the editable install still serves the
  old version (stale dist-info directory left in site-packages)
- Multiple dist-info directories for superharness coexist in site-packages,
  causing importlib.metadata to return an unpredictable version
"""
from __future__ import annotations

import site
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _pyproject_version(repo_root: Path) -> str:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text())
    return data["project"]["version"]


def _superharness_dist_infos() -> list[Path]:
    dirs: list[Path] = []
    for sp in site.getsitepackages():
        dirs.extend(Path(sp).glob("superharness-*.dist-info"))
    user_sp = site.getusersitepackages()
    if user_sp:
        dirs.extend(Path(user_sp).glob("superharness-*.dist-info"))
    return dirs


def test_installed_version_matches_pyproject(repo_root: Path) -> None:
    """importlib.metadata must return the version declared in pyproject.toml.

    Fails when pip install -e . leaves a stale dist-info from a prior version.
    Fix: run scripts/dev-reinstall.sh to wipe stale dist-info then reinstall.
    """
    try:
        installed = version("superharness")
    except PackageNotFoundError:
        # Not installed in this environment (e.g. bare CI with PYTHONPATH only).
        # Skip rather than fail — the test is only meaningful for editable installs.
        return

    expected = _pyproject_version(repo_root)
    assert installed == expected, (
        f"Installed superharness=={installed} but pyproject.toml declares {expected}. "
        "Run: bash scripts/dev-reinstall.sh"
    )


def test_no_duplicate_dist_info() -> None:
    """There must be at most one superharness dist-info directory in site-packages.

    Multiple dist-info dirs exist when an old editable install is not cleaned up
    before a pip install of a newer version.  importlib.metadata picks one
    arbitrarily, so the wrong version may be reported.
    """
    dist_infos = _superharness_dist_infos()
    assert len(dist_infos) <= 1, (
        f"Multiple superharness dist-info directories found — stale install:\n"
        + "\n".join(f"  {p}" for p in dist_infos)
        + "\nFix: run scripts/dev-reinstall.sh"
    )
