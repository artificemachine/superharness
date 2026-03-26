"""ntfy notification module actions — send notifications on task events."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Try to import requests, but don't fail if not available
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.debug("requests library not available, ntfy notifications disabled")


def ntfy_send(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Send notification via ntfy server.

    Args:
        context: Context dict with task_id, event, summary, status (optional)
        settings: Module settings with url, topic_env, priority

    Returns:
        Result dict with success status and message
    """
    # Check if requests library is available
    if not HAS_REQUESTS:
        logger.debug("requests library not available, skipping ntfy notification")
        return {
            "success": False,
            "message": "requests library not installed",
            "skipped": True,
        }

    # Get ntfy topic from environment
    topic_env = settings.get("topic_env", "NTFY_TOPIC")
    topic = os.environ.get(topic_env)

    if not topic:
        logger.debug(f"Environment variable {topic_env} not set, skipping ntfy notification")
        return {
            "success": False,
            "message": f"{topic_env} not set",
            "skipped": True,
        }

    # Get ntfy server URL
    url = settings.get("url", "https://ntfy.sh")
    topic_url = f"{url}/{topic}"

    # Get priority
    priority = settings.get("priority", "default")

    # Build message from context
    task_id = context.get("task_id", "unknown")
    event = context.get("event", "unknown")
    summary = context.get("summary", f"Task {task_id} event: {event}")

    # Construct notification title and body
    if event == "on_verify" and context.get("status") == "fail":
        title = f"⚠️ Verification Failed: {task_id}"
        message = summary
    elif event == "on_close":
        title = f"✅ Task Closed: {task_id}"
        message = summary
    else:
        title = f"📋 Task Event: {task_id}"
        message = summary

    # Prepare headers
    headers = {
        "Title": title,
        "Priority": priority,
    }

    try:
        # Send notification
        logger.info(f"Sending ntfy notification to {topic_url}")
        response = requests.post(
            topic_url,
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )

        if response.status_code == 200:
            logger.info(f"ntfy notification sent successfully to {topic}")
            return {
                "success": True,
                "message": f"Notification sent to {topic}",
            }
        else:
            logger.warning(f"ntfy notification failed: {response.status_code} {response.text}")
            return {
                "success": False,
                "message": f"ntfy server returned {response.status_code}",
            }

    except ConnectionError as e:
        logger.warning(f"ntfy server unreachable: {e}")
        return {
            "success": False,
            "message": "ntfy server unreachable",
            "skipped": True,
        }

    except Exception as e:
        logger.error(f"ntfy notification failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }
