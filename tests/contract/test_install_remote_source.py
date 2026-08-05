"""Public installer source regression tests."""

from pathlib import Path


def test_remote_installer_clones_the_canonical_repository() -> None:
    source = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "install-remote.sh"
    ).read_text()

    assert 'REPO_URL="https://github.com/artificemachine/superharness.git"' in source
    assert "celstnblacc/superharness" not in source


def test_pypi_setup_uses_the_canonical_github_owner() -> None:
    source = (Path(__file__).parents[2] / "docs" / "PYPI_SETUP.md").read_text()

    assert "Owner: `artificemachine`" in source
    assert "https://github.com/artificemachine/superharness" in source
    assert "celstnblacc/superharness" not in source
