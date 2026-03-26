"""Tests for OpenClaw module (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

from unittest.mock import patch



class TestOpenClawModule:
    """Test OpenClaw delegation module."""

    def test_on_delegate_routes_to_openclaw(self, tmp_path):
        """Delegate with target=openclaw → sends task via MCP."""
        from superharness.modules.actions.openclaw import openclaw_send_task

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.1",
            "project_dir": str(project),
            "event": "on_delegate",
            "target": "openclaw",
            "task_title": "Test task for OpenClaw",
            "task_description": "This is a test task to delegate to NemoClaw",
        }

        settings = {
            "mcp_server": "nemoclaw",
            "sandbox_name": "default",
        }

        # Mock MCP tool call
        with patch("superharness.modules.actions.openclaw.call_mcp_tool") as mock_mcp:
            mock_mcp.return_value = {
                "success": True,
                "agent_id": "agent-123",
                "message": "Task sent to NemoClaw sandbox",
            }

            result = openclaw_send_task(context, settings)

        # Verify task was sent via MCP
        assert result["success"] is True
        assert "agent_id" in result
        assert "openclaw" in result.get("message", "").lower() or "nemoclaw" in result.get("message", "").lower()

        # Verify MCP tool was called with correct params
        mock_mcp.assert_called_once()
        call_kwargs = mock_mcp.call_args.kwargs
        assert call_kwargs["server"] == "nemoclaw"
        assert call_kwargs["tool"] == "send_task_to_agent"
        assert "sandbox" in call_kwargs["arguments"]
        assert "task" in call_kwargs["arguments"]

    def test_openclaw_not_available_fails(self, tmp_path):
        """No NemoClaw MCP → clear error with setup instructions."""
        from superharness.modules.actions.openclaw import openclaw_send_task

        project = tmp_path / "proj"
        project.mkdir()

        context = {
            "task_id": "test.2",
            "project_dir": str(project),
            "event": "on_delegate",
            "target": "openclaw",
            "task_title": "Test task",
            "task_description": "Test description",
        }

        settings = {
            "mcp_server": "nemoclaw",
            "sandbox_name": "default",
        }

        # Mock MCP tool call to fail (server not available)
        with patch("superharness.modules.actions.openclaw.call_mcp_tool") as mock_mcp:
            mock_mcp.side_effect = RuntimeError("MCP server 'nemoclaw' not available")

            result = openclaw_send_task(context, settings)

        # Should fail gracefully with helpful error
        assert result["success"] is False
        assert "not available" in result.get("message", "").lower() or "setup" in result.get("message", "").lower()
