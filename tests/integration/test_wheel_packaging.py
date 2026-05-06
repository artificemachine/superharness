"""Regression test for the missing-adapter-manifests bug.

Bug: pyproject.toml package-data omitted adapter_manifests/*.yaml, so
every pipx-installed wheel shipped with an empty adapter registry. The
dispatcher silently rejected every --to claude-code/codex-cli/gemini-cli
with 'must be one of: none'. The watcher ran but never launched anything.

This test builds a wheel from the repo, installs it into a clean venv,
and asserts the adapter manifests are present and discoverable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import sysconfig
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
EXPECTED_ADAPTERS = {"claude-code", "codex-cli", "gemini-cli"}


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory) -> Path:
    """Build a wheel of the repo into a temp dir."""
    out = tmp_path_factory.mktemp("wheel")
    res = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out)],
        cwd=str(REPO_ROOT), capture_output=True, text=True, check=False, timeout=180,
    )
    if res.returncode != 0:
        pytest.skip(f"wheel build failed (build module may be missing): {res.stderr[:500]}")
    wheels = list(out.glob("superharness-*.whl"))
    assert wheels, f"no wheel produced in {out}"
    return wheels[0]


def test_built_wheel_contains_adapter_manifests(built_wheel: Path):
    """Open the wheel and assert all adapter manifests are present."""
    import zipfile
    with zipfile.ZipFile(built_wheel) as z:
        names = set(z.namelist())
    for adapter in EXPECTED_ADAPTERS:
        path = f"superharness/adapter_manifests/{adapter}.yaml"
        assert path in names, (
            f"wheel is missing {path}.\n"
            f"This is the same bug that broke v1.45.x and v1.46.x dispatch.\n"
            f"Fix: add 'adapter_manifests/*.yaml' to "
            f"[tool.setuptools.package-data] in pyproject.toml.\n"
            f"Wheel contents (first 30): {sorted(names)[:30]}"
        )


def test_installed_wheel_list_adapters_returns_all_three(built_wheel: Path, tmp_path):
    """Install the wheel into a clean venv and assert list_adapters() returns
    the expected three names. Exercises the real import path."""
    venv_dir = tmp_path / "venv"
    venv.create(str(venv_dir), with_pip=True)
    if sys.platform == "win32":
        py = venv_dir / "Scripts" / "python.exe"
    else:
        py = venv_dir / "bin" / "python"
    pip_install = subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", str(built_wheel)],
        capture_output=True, text=True, check=False, timeout=180,
    )
    assert pip_install.returncode == 0, f"pip install failed: {pip_install.stderr[:500]}"

    res = subprocess.run(
        [str(py), "-c",
         "from superharness.engine.adapter_registry import list_adapters; "
         "import json, sys; print(json.dumps(list_adapters()))"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    assert res.returncode == 0, f"list_adapters call failed: {res.stderr}"
    import json
    adapters = set(json.loads(res.stdout.strip()))
    assert adapters == EXPECTED_ADAPTERS, (
        f"Installed wheel exposes adapters={adapters}, expected {EXPECTED_ADAPTERS}. "
        f"Missing: {EXPECTED_ADAPTERS - adapters}"
    )
