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
