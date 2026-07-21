"""Tests for shux explain — zero-setup one-screen pitch."""
from __future__ import annotations

import pytest
from click.testing import CliRunner


@pytest.fixture
def runner():
    return CliRunner()


def test_explain_prints_to_stdout(runner):
    """Output contains the core pitch — 'multi-agent'."""
    from superharness.cli import main
    result = runner.invoke(main, ["explain"])
    assert result.exit_code == 0
    assert "multi-agent" in result.output


def test_explain_exits_zero(runner):
    """explain always exits 0 — it is informational only."""
    from superharness.cli import main
    result = runner.invoke(main, ["explain"])
    assert result.exit_code == 0


def test_explain_no_project_required(tmp_path, runner):
    """explain works without a .superharness/ directory."""
    from superharness.cli import main
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(main, ["explain"])
    assert result.exit_code == 0
    assert "multi-agent" in result.output


def test_explain_mentions_onboard(runner):
    """Output ends with a CTA pointing to shux onboard."""
    from superharness.cli import main
    result = runner.invoke(main, ["explain"])
    assert "shux onboard" in result.output


def test_explain_fits_one_screen(runner):
    """Output is ≤25 lines — must fit a single terminal screen."""
    from superharness.cli import main
    result = runner.invoke(main, ["explain"])
    lines = [l for l in result.output.splitlines() if l.strip()]
    assert len(lines) <= 25, f"explain output is {len(lines)} non-blank lines (max 25)"


@pytest.mark.regression
def test_explain_does_not_claim_contract_yaml_is_source_of_truth(runner):
    """Regression: explain.py said 'contract.yaml — single source of truth'
    long after the project moved to SQLite as the source of truth (YAML is
    export-only). Found by the 2026-07-21 portfolio-ready fresh-clone check —
    the CLI's own onboarding pitch contradicted README.md and CLAUDE.md.
    """
    from superharness.cli import main
    result = runner.invoke(main, ["explain"])
    assert "contract.yaml" not in result.output
    assert "sqlite" in result.output.lower()


def test_explain_aliases(runner):
    """'why' and 'wtf' are registered aliases that also work."""
    from superharness.cli import main
    for alias in ("why", "wtf"):
        result = runner.invoke(main, [alias])
        assert result.exit_code == 0, f"alias '{alias}' failed: {result.output}"
        assert "multi-agent" in result.output, f"alias '{alias}' missing core pitch"
