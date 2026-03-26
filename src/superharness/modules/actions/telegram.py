"""Telegram notification module actions — send notifications on task events."""
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
    logger.debug("requests library not available, telegram notifications disabled")


def telegram_send(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Send notification via Telegram Bot API.

    Args:
        context: Context dict with task_id, event, summary, task_url (optional)
        settings: Module settings with token_env, chat_id_env

    Returns:
        Result dict with success status and message
    """
    # Check if requests library is available
    if not HAS_REQUESTS:
        logger.debug("requests library not available, skipping telegram notification")
        return {
            "success": False,
            "message": "requests library not installed",
            "skipped": True,
        }

    # Get Telegram bot token from environment
    token_env = settings.get("token_env", "TELEGRAM_BOT_TOKEN")
    token = os.environ.get(token_env)

    if not token:
        logger.debug(f"Environment variable {token_env} not set, skipping telegram notification")
        return {
            "success": False,
            "message": f"{token_env} not set",
            "skipped": True,
        }

    # Get Telegram chat ID from environment
    chat_id_env = settings.get("chat_id_env", "TELEGRAM_CHAT_ID")
    chat_id = os.environ.get(chat_id_env)

    if not chat_id:
        logger.debug(f"Environment variable {chat_id_env} not set, skipping telegram notification")
        return {
            "success": False,
            "message": f"{chat_id_env} not set",
            "skipped": True,
        }

    # Build API URL
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Build message from context
    task_id = context.get("task_id", "unknown")
    event = context.get("event", "unknown")
    summary = context.get("summary", f"Task {task_id} event: {event}")
    task_url = context.get("task_url")

    # Construct notification message
    if event == "on_close":
        message = f"✅ *Task Closed*\n\n`{task_id}`\n\n{summary}"
    elif event == "on_delegate":
        message = f"📋 *Task Delegated*\n\n`{task_id}`\n\n{summary}"
        if task_url:
            message += f"\n\n🔗 [View Task]({task_url})"
    else:
        message = f"📌 *Task Event*\n\n`{task_id}`\n\n{summary}"

    # Prepare request payload
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        # Send message
        logger.info(f"Sending telegram notification for task {task_id}")
        response = requests.post(
            api_url,
            json=payload,
            timeout=10,
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                logger.info(f"Telegram notification sent successfully for {task_id}")
                return {
                    "success": True,
                    "message": f"Telegram notification sent for {task_id}",
                }
            else:
                logger.warning(f"Telegram API returned error: {result}")
                return {
                    "success": False,
                    "message": f"Telegram API error: {result.get('description', 'Unknown error')}",
                }
        else:
            logger.warning(f"Telegram notification failed: {response.status_code} {response.text}")
            return {
                "success": False,
                "message": f"Telegram API returned {response.status_code}",
            }

    except ConnectionError as e:
        logger.warning(f"Telegram API unreachable: {e}")
        return {
            "success": False,
            "message": "Telegram API unreachable",
            "skipped": True,
        }

    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }
