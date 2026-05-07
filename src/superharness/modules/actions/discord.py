"""Discord notification module actions — send notifications on task events."""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    logger.debug("requests library not available, discord notifications disabled")


def discord_send(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Send a notification to a Discord channel via webhook.

    Args:
        context: Context dict with task_id, event, summary, task_url (optional).
        settings: Module settings with webhook_url_env.

    Returns:
        Result dict with success status and message.
    """
    if not HAS_REQUESTS:
        logger.debug("requests library not available, skipping discord notification")
        return {
            "success": False,
            "message": "requests library not installed",
            "skipped": True,
        }

    webhook_env = settings.get("webhook_url_env", "DISCORD_WEBHOOK_URL")
    webhook_url = os.environ.get(webhook_env)

    if not webhook_url:
        logger.debug("%s not set, skipping discord notification", webhook_env)
        return {
            "success": False,
            "message": f"{webhook_env} not set",
            "skipped": True,
        }

    task_id = context.get("task_id", "unknown")
    event = context.get("event", "unknown")
    summary = context.get("summary", f"Task {task_id} event: {event}")
    task_url = context.get("task_url")

    if event == "on_close":
        content = f"✅ **Task Closed** `{task_id}`\n{summary}"
    elif event == "on_delegate":
        content = f"📋 **Task Delegated** `{task_id}`\n{summary}"
        if task_url:
            content += f"\n🔗 {task_url}"
    elif event == "on_fail":
        content = f"❌ **Task Failed** `{task_id}`\n{summary}"
    else:
        content = f"📌 **Task Event** `{task_id}` ({event})\n{summary}"

    try:
        resp = requests.post(
            webhook_url,
            json={"content": content},
            timeout=10,
        )
        resp.raise_for_status()
        return {"success": True, "message": "sent", "status_code": resp.status_code}
    except Exception as exc:
        logger.warning("discord_send failed: %s", exc)
        return {"success": False, "message": str(exc)}


def discord_trigger(settings: dict[str, Any]) -> dict[str, Any]:
    """Poll a Discord channel for incoming dispatch trigger messages.

    This is a lightweight pull-based trigger: it reads the last N messages
    from a channel via the Discord REST API and returns any that look like
    superharness dispatch commands (e.g. ``!dispatch <task-id>``).

    Args:
        settings: Module settings with bot_token_env, channel_id_env, limit.

    Returns:
        Dict with ``triggers`` list (each item has ``task_id``, ``agent``,
        ``raw``) and ``success`` bool.
    """
    if not HAS_REQUESTS:
        return {
            "success": False,
            "message": "requests library not installed",
            "triggers": [],
            "skipped": True,
        }

    token_env = settings.get("bot_token_env", "DISCORD_BOT_TOKEN")
    channel_env = settings.get("channel_id_env", "DISCORD_CHANNEL_ID")
    token = os.environ.get(token_env)
    channel_id = os.environ.get(channel_env)
    limit = int(settings.get("limit", 10))

    if not token:
        return {"success": False, "message": f"{token_env} not set", "triggers": [], "skipped": True}
    if not channel_id:
        return {"success": False, "message": f"{channel_env} not set", "triggers": [], "skipped": True}

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    headers = {"Authorization": f"Bot {token}"}

    try:
        resp = requests.get(url, headers=headers, params={"limit": limit}, timeout=10)
        resp.raise_for_status()
        messages = resp.json()
    except Exception as exc:
        logger.warning("discord_trigger poll failed: %s", exc)
        return {"success": False, "message": str(exc), "triggers": []}

    triggers = []
    for msg in messages:
        content = msg.get("content", "").strip()
        if content.startswith("!dispatch "):
            parts = content.split()
            task_id = parts[1] if len(parts) > 1 else None
            agent = parts[2] if len(parts) > 2 else None
            if task_id:
                triggers.append({"task_id": task_id, "agent": agent, "raw": content})

    return {"success": True, "triggers": triggers, "message": f"{len(triggers)} trigger(s) found"}
