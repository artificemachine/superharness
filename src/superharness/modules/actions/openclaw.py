"""OpenClaw module actions — delegate tasks to NemoClaw sandboxed agents."""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def call_mcp_tool(server: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool via the MCP server.

    This is a placeholder implementation. In production, this would:
    - Connect to the MCP server via stdio/HTTP
    - Send JSON-RPC request for tool invocation
    - Return parsed response

    For now, we just raise an error to simulate MCP server not being available.

    Args:
        server: MCP server name (e.g., "nemoclaw")
        tool: Tool name (e.g., "send_task_to_agent")
        arguments: Tool arguments dict

    Returns:
        Tool response dict

    Raises:
        RuntimeError: If MCP server is not available
    """
    # TODO: Implement actual MCP client communication
    # For now, this simulates the MCP server not being available
    raise RuntimeError(f"MCP server '{server}' not available")


def openclaw_send_task(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Send task to OpenClaw agent via NemoClaw MCP server.

    Args:
        context: Context dict with task_id, task_title, task_description, target
        settings: Module settings with mcp_server, sandbox_name

    Returns:
        Result dict with success status, agent_id (if successful), and message
    """
    task_id = context.get("task_id", "unknown")
    task_title = context.get("task_title", "")
    task_description = context.get("task_description", "")

    # Get settings
    mcp_server = settings.get("mcp_server", "nemoclaw")
    sandbox_name = settings.get("sandbox_name", "default")

    # Build task prompt for OpenClaw agent
    task_prompt = f"""Task ID: {task_id}
Title: {task_title}

{task_description}

Please execute this task and report back with results."""

    # Prepare MCP tool arguments
    tool_args = {
        "sandbox": sandbox_name,
        "task": task_prompt,
        "timeout": 120,  # 2 minute timeout
    }

    try:
        # Call MCP tool to send task to agent
        logger.info(f"Sending task {task_id} to OpenClaw agent in sandbox '{sandbox_name}'")

        result = call_mcp_tool(
            server=mcp_server,
            tool="send_task_to_agent",
            arguments=tool_args,
        )

        # Extract agent ID from result
        agent_id = result.get("agent_id", "unknown")

        logger.info(f"Task {task_id} sent to OpenClaw agent {agent_id}")
        return {
            "success": True,
            "agent_id": agent_id,
            "message": f"Task sent to NemoClaw sandbox '{sandbox_name}'",
        }

    except RuntimeError as e:
        # MCP server not available
        error_msg = str(e)
        logger.warning(f"Failed to send task to OpenClaw: {error_msg}")

        # Return helpful error message
        return {
            "success": False,
            "message": (
                "OpenClaw MCP server not available. "
                "Setup instructions: install clawctl MCP bridge from "
                "github.com/celstnblacc/clawctl and register with Claude Code."
            ),
        }

    except Exception as e:
        # Unexpected error
        logger.error(f"Failed to send task to OpenClaw: {e}")
        return {
            "success": False,
            "message": f"Failed to send task: {e}",
        }
