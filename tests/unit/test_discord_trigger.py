"""Tests for modules/actions/discord.py — Phase 3 Discord adapter."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# discord_send — missing env vars
# ---------------------------------------------------------------------------


def test_discord_send_missing_webhook_skips():
    from superharness.modules.actions.discord import discord_send

    result = discord_send(
        context={"task_id": "t1", "event": "on_close", "summary": "done"},
        settings={"webhook_url_env": "DISCORD_WEBHOOK_URL_MISSING_XYZ"},
    )
    assert result["success"] is False
    assert result.get("skipped") is True


def test_discord_send_no_requests_skips(monkeypatch):
    import superharness.modules.actions.discord as mod

    monkeypatch.setattr(mod, "HAS_REQUESTS", False)
    result = mod.discord_send(
        context={"task_id": "t1", "event": "on_close"},
        settings={},
    )
    assert result["success"] is False
    assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# discord_send — successful HTTP call
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# discord_trigger — missing env vars
# ---------------------------------------------------------------------------


def test_discord_trigger_missing_token_skips():
    from superharness.modules.actions.discord import discord_trigger

    result = discord_trigger(
        settings={"bot_token_env": "DISCORD_BOT_TOKEN_MISSING_XYZ"}
    )
    assert result["success"] is False
    assert result.get("skipped") is True
    assert result["triggers"] == []


def test_discord_trigger_missing_channel_skips(monkeypatch):
    import superharness.modules.actions.discord as mod

    monkeypatch.setattr(mod, "HAS_REQUESTS", True)
    monkeypatch.setenv("DISCORD_TEST_BOT_TOKEN", "fake-token")

    result = mod.discord_trigger(
        settings={
            "bot_token_env": "DISCORD_TEST_BOT_TOKEN",
            "channel_id_env": "DISCORD_CHANNEL_MISSING_XYZ",
        }
    )
    assert result["success"] is False
    assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# discord_trigger — parse dispatch commands
# ---------------------------------------------------------------------------


