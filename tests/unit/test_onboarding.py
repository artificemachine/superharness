"""Tests for onboarding UX: shux --help quickstart and demo command-first flow."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class TestShuxHelpQuickstart:
    """RED: shux --help should show clear first-commands quickstart."""

    def test_help_shows_quickstart_section(self):
        """shux --help output includes a 'Quick Start' or 'First Commands' section."""
        result = subprocess.run(
            [sys.executable, "-m", "superharness", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        output = result.stdout.lower()
        # Check for quickstart-related headers
        assert any(marker in output for marker in ["quick start", "first commands", "getting started"])

    def test_help_shows_init_first(self):
        """shux --help quickstart section mentions 'shux init' as first step."""
        result = subprocess.run(
            [sys.executable, "-m", "superharness", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        output = result.stdout
        # Check that init is mentioned
        assert "init" in output.lower()

    def test_help_shows_core_commands(self):
        """shux --help quickstart mentions core commands: init, doctor, contract, delegate."""
        result = subprocess.run(
            [sys.executable, "-m", "superharness", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        output = result.stdout.lower()
        # Core workflow commands should be visible
        for cmd in ["init", "doctor", "contract", "delegate"]:
            assert cmd in output


class TestDemoCommandFirst:
    """RED: shux demo should guide new users through command-first flow."""

    def test_demo_runs_without_agent_cli(self):
        """shux demo completes successfully without requiring agent CLI installation."""
        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.demo"],
            capture_output=True,
            text=True,
        )
        # Demo should succeed (exit 0) even without agent CLI
        assert result.returncode == 0

    def test_demo_shows_command_first_flow(self):
        """shux demo output demonstrates the command-first workflow steps."""
        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.demo"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        output = result.stdout.lower()

        # Should show the key workflow steps
        assert "init" in output
        assert "task" in output or "create" in output
        assert "enqueue" in output or "delegate" in output

    def test_demo_output_mentions_next_steps(self):
        """shux demo ends with clear next steps for real projects."""
        result = subprocess.run(
            [sys.executable, "-m", "superharness.commands.demo"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        output = result.stdout.lower()

        # Should provide guidance on what to do next
        assert "next" in output or "try" in output
        # Should mention real project usage
        assert "project" in output


class TestWindowsDocumentation:
    """RED: Documentation should include Windows + pipx copy-paste onboarding."""

    def test_readme_has_windows_install_section(self):
        """README.md includes Windows-specific installation instructions."""
        readme = Path(__file__).parent.parent.parent / "README.md"
        content = readme.read_text().lower()

        # Should mention Windows or provide cross-platform install
        assert "pipx" in content
        # Windows users need pipx or pip install instructions
        assert "install" in content

    def test_readme_pipx_install_copy_pasteable(self):
        """README.md provides a single pipx install command users can copy-paste."""
        readme = Path(__file__).parent.parent.parent / "README.md"
        content = readme.read_text()

        # Should have the exact install command
        assert "pipx install superharness" in content

    def test_install_agent_doc_mentions_windows(self):
        """docs/INSTALL-AGENT.md includes Windows compatibility notes."""
        install_doc = Path(__file__).parent.parent.parent / "docs" / "INSTALL-AGENT.md"
        if install_doc.exists():
            content = install_doc.read_text().lower()
            # Cross-platform or explicit Windows mention
            assert any(marker in content for marker in ["windows", "cross-platform", "pipx"])


class TestOnboardingDocsCheck:
    """RED: Focused tests/docs checks for new onboarding flow."""

    def test_guide_mentions_command_first_workflow(self):
        """docs/GUIDE.md emphasizes the command-first (no agent CLI) onboarding path."""
        guide = Path(__file__).parent.parent.parent / "docs" / "GUIDE.md"
        if guide.exists():
            content = guide.read_text().lower()
            # Should reference the new workflow
            assert "command" in content or "shux" in content

    def test_readme_quickstart_matches_help_output(self):
        """README quickstart section aligns with shux --help quickstart."""
        readme = Path(__file__).parent.parent.parent / "README.md"
        content = readme.read_text().lower()

        # Core workflow commands should be documented
        for cmd in ["init", "doctor", "contract"]:
            assert cmd in content
