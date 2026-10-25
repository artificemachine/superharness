"""cli/status.sh reports the package version from pyproject.toml, the one version source."""

import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("bash") is None, reason="requires bash")
def test_status_header_uses_pyproject_version(tmp_path: Path) -> None:
    with (REPO / "pyproject.toml").open("rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]

    result = subprocess.run(
        ["bash", str(REPO / "cli" / "status.sh"), "--project", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    header = result.stdout.splitlines()[0]
    assert header.startswith(f"superharness v{expected} "), header
