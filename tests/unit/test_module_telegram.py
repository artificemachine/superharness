"""Tests for telegram module (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

from unittest.mock import Mock, patch



class TestTelegramModule:
    """Test Telegram notification module."""

    def test_on_close_sends_summary(self, tmp_path):
        """Close fires → Telegram message with task summary."""
        from superharness.modules.actions.telegram import telegram_send

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.1",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Task test.1 completed successfully",
        }

        settings = {
            "token_env": "TELEGRAM_BOT_TOKEN",
            "chat_id_env": "TELEGRAM_CHAT_ID",
        }

        # Mock environment variables
        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": "test-token-123",
            "TELEGRAM_CHAT_ID": "12345678"
        }):
            # Mock requests.post to simulate successful Telegram API call
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}

            # Mock both HAS_REQUESTS flag and requests module
            with patch("superharness.modules.actions.telegram.HAS_REQUESTS", True):
                with patch("superharness.modules.actions.telegram.requests", create=True) as mock_requests:
                    mock_requests.post.return_value = mock_response
                    result = telegram_send(context, settings)

                    # Verify message was sent
                    assert result["success"] is True
                    assert "sent" in result.get("message", "").lower()

                    # Verify correct Telegram API endpoint was called
                    mock_requests.post.assert_called_once()
                    call_args = mock_requests.post.call_args
                    assert "api.telegram.org" in call_args[0][0]
                    assert "test-token-123" in call_args[0][0]
                    assert "sendMessage" in call_args[0][0]

    def test_on_delegate_sends_link(self, tmp_path):
        """Delegate fires → Telegram message with task link."""
        from superharness.modules.actions.telegram import telegram_send

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.2",
            "project_dir": str(project),
            "event": "on_delegate",
            "summary": "Task test.2 delegated to agent",
            "task_url": "https://example.com/tasks/test.2",
        }

        settings = {
            "token_env": "TELEGRAM_BOT_TOKEN",
            "chat_id_env": "TELEGRAM_CHAT_ID",
        }

        # Mock environment variables
        with patch.dict("os.environ", {
            "TELEGRAM_BOT_TOKEN": "test-token-123",
            "TELEGRAM_CHAT_ID": "12345678"
        }):
            # Mock requests.post to simulate successful Telegram API call
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}

            # Mock both HAS_REQUESTS flag and requests module
            with patch("superharness.modules.actions.telegram.HAS_REQUESTS", True):
                with patch("superharness.modules.actions.telegram.requests", create=True) as mock_requests:
                    mock_requests.post.return_value = mock_response
                    result = telegram_send(context, settings)

                    # Verify message was sent
                    assert result["success"] is True

                    # Verify message contains task link
                    mock_requests.post.assert_called_once()
                    call_args = mock_requests.post.call_args
                    message_text = call_args[1]["json"]["text"]
                    assert "example.com/tasks/test.2" in message_text

    def test_no_token_disables(self, tmp_path):
        """No TELEGRAM_BOT_TOKEN → module auto-disables."""
        from superharness.modules.actions.telegram import telegram_send

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.3",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Task test.3 completed",
        }

        settings = {
            "token_env": "TELEGRAM_BOT_TOKEN",
            "chat_id_env": "TELEGRAM_CHAT_ID",
        }

        # No environment variables set
        # Mock HAS_REQUESTS to simulate requests library being available
        # but no token is set
        with patch.dict("os.environ", {}, clear=True):
            with patch("superharness.modules.actions.telegram.HAS_REQUESTS", True):
                result = telegram_send(context, settings)

        # Should skip gracefully without crashing
        assert result["success"] is False
        assert result.get("skipped") is True
        assert "TELEGRAM_BOT_TOKEN" in result.get("message", "")
