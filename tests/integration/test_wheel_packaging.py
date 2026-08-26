"""Regression test for the missing-adapter-manifests bug.

Bug: pyproject.toml package-data omitted adapter_manifests/*.yaml, so
every pipx-installed wheel shipped with an empty adapter registry. The
dispatcher silently rejected every --to claude-code/codex-cli/gemini-cli
with 'must be one of: none'. The watcher ran but never launched anything.

This test builds a wheel from the repo, installs it into a clean venv,
and asserts the adapter manifests are present and discoverable.
"""

from __future__ import annotations

import subprocess
import sys
import venv
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


def _manifest_names(manifests: Path) -> list[str]:
    return sorted(path.stem for path in manifests.glob("*.yaml"))


def _bundled_manifest_names() -> list[str]:
    return _manifest_names(REPO_ROOT / "src/superharness/adapter_manifests")


def test_expected_adapters_match_bundled_manifests(tmp_path) -> None:
    manifests = tmp_path / "adapter_manifests"
    manifests.mkdir()
    (manifests / "stable.yaml").write_text("name: stable\n")
    (manifests / "experimental-pi.yaml").write_text("name: experimental-pi\n")
    (manifests / "README.md").write_text("not a manifest\n")

    assert _manifest_names(manifests) == ["experimental-pi", "stable"]
    assert _bundled_manifest_names()


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory) -> Path:
    """Build a wheel of the repo into a temp dir."""
    out = tmp_path_factory.mktemp("wheel")
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--outdir",
            str(out),
            str(REPO_ROOT),
        ],
        # Run outside the source tree: a prior setuptools build may leave an
        # ignored ``build/`` directory that shadows the third-party ``build``
        # module when Python is invoked from the repository root.
        cwd=str(out),
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert res.returncode == 0, f"wheel build failed: {res.stderr[:500]}"
    wheels = list(out.glob("superharness-*.whl"))
    assert wheels, f"no wheel produced in {out}"
    return wheels[0]


def test_built_wheel_contains_adapter_manifests(built_wheel: Path):
    """Open the wheel and assert all adapter manifests are present."""
    import zipfile

    with zipfile.ZipFile(built_wheel) as z:
        names = set(z.namelist())
    for adapter in _bundled_manifest_names():
        path = f"superharness/adapter_manifests/{adapter}.yaml"
        assert path in names, (
            f"wheel is missing {path}.\n"
            f"This is the same bug that broke v1.45.x and v1.46.x dispatch.\n"
            f"Fix: add 'adapter_manifests/*.yaml' to "
            f"[tool.setuptools.package-data] in pyproject.toml.\n"
            f"Wheel contents (first 30): {sorted(names)[:30]}"
        )


def test_installed_wheel_list_adapters_returns_all_supported(
    built_wheel: Path, tmp_path
):
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
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert pip_install.returncode == 0, (
        f"pip install failed: {pip_install.stderr[:500]}"
    )

    res = subprocess.run(
        [
            str(py),
            "-c",
            "from superharness.engine.adapter_registry import list_adapters; "
            "import json, sys; print(json.dumps(list_adapters()))",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert res.returncode == 0, f"list_adapters call failed: {res.stderr}"
    import json

    adapters = set(json.loads(res.stdout.strip()))
    expected_adapters = set(_bundled_manifest_names())
    assert adapters == expected_adapters, (
        f"Installed wheel exposes adapters={adapters}, expected {expected_adapters}. "
        f"Missing: {expected_adapters - adapters}"
    )


# ---------------------------------------------------------------------------
# All bundled adapters are shipped in the wheel
# ---------------------------------------------------------------------------


def test_wheel_includes_all_bundled_manifests(built_wheel):
    """Every repository manifest, including experimental adapters, ships in the wheel."""
    import zipfile

    with zipfile.ZipFile(built_wheel) as z:
        names = set(z.namelist())
    for adapter in _bundled_manifest_names():
        assert f"superharness/adapter_manifests/{adapter}.yaml" in names, (
            f"wheel missing manifest for {adapter}. "
            f"Repository adapters must be installable from the wheel."
        )
