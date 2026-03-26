"""Tests for security module (TDD — RED phase)."""
from __future__ import annotations

from unittest.mock import Mock, patch



class TestSecurityModule:
    """Test security module (shipguard gate)."""

    def test_detect_shipguard(self, tmp_path):
        """shipguard binary found → module available."""
        from superharness.modules.actions.security import detect_security_scanner

        # Mock shutil.which to simulate shipguard available
        with patch("shutil.which", return_value="/usr/local/bin/shipguard"):
            result = detect_security_scanner()
            assert result == "shipguard"

    def test_on_verify_runs_shipguard(self, tmp_path):
        """Verify fires → shipguard scan runs, result included in verification."""
        from superharness.modules.actions.security import security_scan

        project = tmp_path / "proj"
        project.mkdir()
        (project / ".git").mkdir()  # Make it a git repo

        context = {
            "task_id": "test.1",
            "project_dir": str(project),
        }

        settings = {
            "severity_threshold": "high",
        }

        # Mock subprocess to simulate shipguard success
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "No critical findings"
        mock_result.stderr = ""

        with patch("superharness.modules.actions.security.shutil.which", return_value="/usr/local/bin/shipguard"):
            with patch("subprocess.run", return_value=mock_result):
                result = security_scan(context, settings)

        assert result["success"] is True
        assert "scan_output" in result

    def test_on_verify_critical_blocks(self, tmp_path):
        """Critical finding → verify returns fail."""
        from superharness.modules.actions.security import security_scan

        project = tmp_path / "proj"
        project.mkdir()
        (project / ".git").mkdir()

        context = {
            "task_id": "test.2",
            "project_dir": str(project),
        }

        settings = {
            "severity_threshold": "high",
        }

        # Mock subprocess to simulate shipguard finding critical issue
        mock_result = Mock()
        mock_result.returncode = 1  # Non-zero = findings
        mock_result.stdout = "CRITICAL: Hardcoded secret detected"
        mock_result.stderr = ""

        with patch("superharness.modules.actions.security.shutil.which", return_value="/usr/local/bin/shipguard"):
            with patch("subprocess.run", return_value=mock_result):
                result = security_scan(context, settings)

        assert result["success"] is False
        assert "blocked" in result
        assert result["blocked"] is True

    def test_on_verify_no_shipguard_skips(self, tmp_path):
        """shipguard not found → skip silently."""
        from superharness.modules.actions.security import security_scan

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.3",
            "project_dir": str(project),
        }

        settings = {
            "severity_threshold": "high",
        }

        # Mock shutil.which to simulate no shipguard
        with patch("shutil.which", return_value=None):
            result = security_scan(context, settings)

        # Should skip gracefully
        assert result["success"] is False
        assert "skipped" in result or "not found" in result.get("message", "").lower()
