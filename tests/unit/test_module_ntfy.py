"""Tests for ntfy module (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

import pytest
pytest.importorskip("requests")

from unittest.mock import Mock, patch



class TestNtfyModule:
    """Test ntfy notification module."""

    def test_on_close_sends_notification(self, tmp_path):
        """Close fires → ntfy push with task summary."""
        from superharness.modules.actions.ntfy import ntfy_send

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.1",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Task test.1 completed successfully",
        }

        settings = {
            "url": "https://ntfy.sh",
            "topic_env": "NTFY_TOPIC",
            "priority": "default",
        }

        # Mock environment variable
        with patch.dict("os.environ", {"NTFY_TOPIC": "test-topic"}):
            # Mock requests.post to simulate successful notification
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"

            with patch("requests.post", return_value=mock_response) as mock_post:
                result = ntfy_send(context, settings)

            # Verify notification was sent
            assert result["success"] is True
            assert "sent" in result.get("message", "").lower()

            # Verify correct URL and data
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert "ntfy.sh/test-topic" in call_args[0][0]

    def test_on_verify_fail_sends_alert(self, tmp_path):
        """Verify fail → high-priority ntfy alert."""
        from superharness.modules.actions.ntfy import ntfy_send

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.2",
            "project_dir": str(project),
            "event": "on_verify",
            "status": "fail",
            "summary": "Verification failed for test.2",
        }

        settings = {
            "url": "https://ntfy.sh",
            "topic_env": "NTFY_TOPIC",
            "priority": "high",
        }

        # Mock environment variable
        with patch.dict("os.environ", {"NTFY_TOPIC": "test-topic"}):
            # Mock requests.post to simulate successful notification
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.text = "OK"

            with patch("requests.post", return_value=mock_response) as mock_post:
                result = ntfy_send(context, settings)

            # Verify notification was sent with high priority
            assert result["success"] is True

            # Verify high priority was set in headers
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[1]["headers"]["Priority"] == "high"

    def test_ntfy_unavailable_skips(self, tmp_path):
        """ntfy server unreachable → skip, no crash."""
        from superharness.modules.actions.ntfy import ntfy_send

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.3",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Task test.3 completed",
        }

        settings = {
            "url": "https://ntfy.sh",
            "topic_env": "NTFY_TOPIC",
            "priority": "default",
        }

        # Mock environment variable
        with patch.dict("os.environ", {"NTFY_TOPIC": "test-topic"}):
            # Mock requests.post to simulate connection error
            with patch("requests.post", side_effect=ConnectionError("Server unreachable")):
                result = ntfy_send(context, settings)

            # Should skip gracefully without crashing
            assert result["success"] is False
            assert "skipped" in result or "unreachable" in result.get("message", "").lower()
