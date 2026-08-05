"""Regression guard for dashboard timeout test isolation."""

from pathlib import Path


def test_dashboard_timeout_uses_a_temporary_project() -> None:
    """A user's live dashboard must not affect the timeout regression tests."""
    source = (Path(__file__).parents[1] / "test_dashboard_timeout.py").read_text()

    assert source.count("tmp_path") >= 2
    assert "project_dir = Path(__file__).parent.parent.resolve()" not in source
