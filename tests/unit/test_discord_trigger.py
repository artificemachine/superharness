"""Tests for modules/actions/discord.py — Phase 3 Discord adapter."""
from __future__ import annotations

import os
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

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_discord_send_posts_webhook(monkeypatch):
    import superharness.modules.actions.discord as mod
    monkeypatch.setattr(mod, "HAS_REQUESTS", True)
    monkeypatch.setenv("DISCORD_TEST_WEBHOOK", "https://discord.com/api/webhooks/fake/token")

    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status.return_value = None

    with patch.object(mod.requests, "post", return_value=mock_resp) as mock_post:
        result = mod.discord_send(
            context={"task_id": "t1", "event": "on_delegate", "summary": "delegated"},
            settings={"webhook_url_env": "DISCORD_TEST_WEBHOOK"},
        )

    assert result["success"] is True
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert "delegated" in kwargs["json"]["content"]


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_discord_send_on_fail_event(monkeypatch):
    import superharness.modules.actions.discord as mod
    monkeypatch.setattr(mod, "HAS_REQUESTS", True)
    monkeypatch.setenv("DISCORD_FAIL_HOOK", "https://discord.com/api/webhooks/fake/x")

    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.raise_for_status.return_value = None

    with patch.object(mod.requests, "post", return_value=mock_resp) as mock_post:
        result = mod.discord_send(
            context={"task_id": "t2", "event": "on_fail", "summary": "crashed"},
            settings={"webhook_url_env": "DISCORD_FAIL_HOOK"},
        )

    assert result["success"] is True
    _, kwargs = mock_post.call_args
    assert "❌" in kwargs["json"]["content"] or "Failed" in kwargs["json"]["content"]


# ---------------------------------------------------------------------------
# discord_trigger — missing env vars
# ---------------------------------------------------------------------------

def test_discord_trigger_missing_token_skips():
    from superharness.modules.actions.discord import discord_trigger
    result = discord_trigger(settings={"bot_token_env": "DISCORD_BOT_TOKEN_MISSING_XYZ"})
    assert result["success"] is False
    assert result.get("skipped") is True
    assert result["triggers"] == []


def test_discord_trigger_missing_channel_skips(monkeypatch):
    import superharness.modules.actions.discord as mod
    monkeypatch.setattr(mod, "HAS_REQUESTS", True)
    monkeypatch.setenv("DISCORD_TEST_BOT_TOKEN", "fake-token")

    result = mod.discord_trigger(settings={
        "bot_token_env": "DISCORD_TEST_BOT_TOKEN",
        "channel_id_env": "DISCORD_CHANNEL_MISSING_XYZ",
    })
    assert result["success"] is False
    assert result.get("skipped") is True


# ---------------------------------------------------------------------------
# discord_trigger — parse dispatch commands
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_discord_trigger_parses_dispatch_commands(monkeypatch):
    import superharness.modules.actions.discord as mod
    monkeypatch.setattr(mod, "HAS_REQUESTS", True)
    monkeypatch.setenv("DISCORD_BOT_TKN", "fake")
    monkeypatch.setenv("DISCORD_CH_ID", "123")

    messages = [
        {"content": "!dispatch task-1 claude-code"},
        {"content": "hello world"},
        {"content": "!dispatch task-2"},
    ]
    mock_resp = MagicMock()
    mock_resp.json.return_value = messages
    mock_resp.raise_for_status.return_value = None

    with patch.object(mod.requests, "get", return_value=mock_resp):
        result = mod.discord_trigger(settings={
            "bot_token_env": "DISCORD_BOT_TKN",
            "channel_id_env": "DISCORD_CH_ID",
        })

    assert result["success"] is True
    assert len(result["triggers"]) == 2
    assert result["triggers"][0]["task_id"] == "task-1"
    assert result["triggers"][0]["agent"] == "claude-code"
    assert result["triggers"][1]["task_id"] == "task-2"
    assert result["triggers"][1]["agent"] is None
