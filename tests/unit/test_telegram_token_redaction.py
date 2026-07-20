"""Iteration 1 — Telegram bot token must never reach a logger unredacted.

Covers the 2026-07-20 audit finding: `requests` exceptions carrying the full
`https://api.telegram.org/bot<token>` URL get logged verbatim via
`logger.warning(..., exc_info=True)` / `logger.exception(...)`, which
discloses the credential to anyone who can read the serving logs.
"""
from __future__ import annotations

import logging

import pytest
import requests

from superharness.modules.gateway import telegram_gateway
from superharness.modules.gateway.telegram_gateway import GatewayListener
from superharness.modules.actions import telegram as actions_telegram


TOKEN = "123456789:AAExampleTokenValue-abcDEF1234"


@pytest.fixture
def project_dir(tmp_path):
    harness = tmp_path / ".superharness"
    harness.mkdir()
    return str(tmp_path)


def test_base_url_is_not_logged_verbatim(project_dir, caplog):
    """A requests exception carrying the full bot URL must not leak the token."""
    listener = GatewayListener(
        token=TOKEN,
        allowed_senders=["42"],
        project_dir=project_dir,
        send_replies=False,
    )

    err = requests.exceptions.ConnectionError(
        f"HTTPSConnectionPool(host='api.telegram.org', port=443): "
        f"Max retries exceeded with url: /bot{TOKEN}/getUpdates"
    )

    with caplog.at_level(logging.WARNING, logger="superharness.modules.gateway.telegram_gateway"):
        try:
            raise err
        except requests.exceptions.ConnectionError as e:
            telegram_gateway.logger.warning(
                "telegram_gateway.py unexpected error: %s", e, exc_info=True
            )
            telegram_gateway.logger.exception("getUpdates failed")

    combined = caplog.text
    assert TOKEN not in combined
    assert f"bot{TOKEN}" not in combined


def test_redactor_masks_token_in_arbitrary_string():
    text = "https://api.telegram.org/bot123456:ABC-DEF/getUpdates"
    result = telegram_gateway._redact_token(text)

    assert "123456:ABC-DEF" not in result
    assert "bot<redacted>" in result
    assert result.startswith("https://api.telegram.org/")
    assert result.endswith("/getUpdates")


def test_redactor_is_noop_without_a_token():
    text = "a plain log message with no secrets in it"
    assert telegram_gateway._redact_token(text) == text


def test_actions_telegram_error_path_is_redacted(caplog, monkeypatch):
    """`modules/actions/telegram.py`'s error logging must redact the same URL shape."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    class _BrokenSession:
        def post(self, *args, **kwargs):
            raise requests.exceptions.ConnectionError(
                f"Max retries exceeded with url: /bot{TOKEN}/sendMessage"
            )

    monkeypatch.setattr(actions_telegram, "requests", _BrokenSession())

    with caplog.at_level(logging.WARNING, logger="superharness.modules.actions.telegram"):
        result = actions_telegram.telegram_send(
            context={"task_id": "t-1", "event": "on_close", "summary": "done"},
            settings={},
        )

    assert result["success"] is False
    combined = caplog.text
    assert TOKEN not in combined
    assert f"bot{TOKEN}" not in combined
