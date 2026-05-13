"""Tests for I6: Gateway listener process.

Acceptance criteria:
  - unknown sender rejected, no row written
  - telegram message_id deduplicates redelivery
  - malformed command sends help reply
  - parse_command handles approve/reject/close/reset
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from superharness.modules.gateway.telegram_gateway import (
    HELP_TEXT,
    KNOWN_COMMANDS,
    GatewayListener,
    ParsedCommand,
    parse_command,
    validate_sender,
)
from superharness.engine.db import get_connection, init_db
from superharness.engine import operator_commands_dao


# ---------------------------------------------------------------------------
# parse_command tests
# ---------------------------------------------------------------------------

class TestParseCommand:
    def test_approve(self):
        result = parse_command("/approve t-abc123")
        assert result == ParsedCommand(command="approve", task_id="t-abc123")

    def test_reject(self):
        result = parse_command("/reject t-abc123")
        assert result == ParsedCommand(command="reject", task_id="t-abc123")

    def test_close(self):
        result = parse_command("/close my-task")
        assert result == ParsedCommand(command="close", task_id="my-task")

    def test_reset(self):
        result = parse_command("/reset t-xyz999")
        assert result == ParsedCommand(command="reset", task_id="t-xyz999")

    def test_botname_suffix_stripped(self):
        result = parse_command("/approve@mybot t-001")
        assert result == ParsedCommand(command="approve", task_id="t-001")

    def test_unknown_command_returns_none(self):
        assert parse_command("/unknown t-abc") is None

    def test_missing_task_id_returns_none(self):
        assert parse_command("/approve") is None
        assert parse_command("/approve   ") is None

    def test_no_slash_returns_none(self):
        assert parse_command("approve t-abc") is None

    def test_empty_returns_none(self):
        assert parse_command("") is None
        assert parse_command(None) is None  # type: ignore[arg-type]

    def test_case_insensitive(self):
        result = parse_command("/APPROVE t-abc")
        assert result == ParsedCommand(command="approve", task_id="t-abc")

    def test_all_known_commands_covered(self):
        for cmd in KNOWN_COMMANDS:
            result = parse_command(f"/{cmd} some-task")
            assert result is not None
            assert result.command == cmd


# ---------------------------------------------------------------------------
# validate_sender tests
# ---------------------------------------------------------------------------

class TestValidateSender:
    def test_known_sender_allowed(self):
        assert validate_sender("12345", ["12345", "99999"])

    def test_unknown_sender_rejected(self):
        assert not validate_sender("99999", ["12345"])

    def test_empty_allowlist_rejects_all(self):
        assert not validate_sender("12345", [])

    def test_int_sender_id_coerced(self):
        assert validate_sender(12345, ["12345"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path):
    harness = tmp_path / ".superharness"
    harness.mkdir()
    return str(tmp_path)


def _make_update(
    message_id: int,
    sender_id: int,
    text: str,
    chat_id: int = 100,
) -> dict:
    return {
        "update_id": message_id,
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id},
            "from": {"id": sender_id},
            "text": text,
        },
    }


def _make_listener(project_dir: str, allowed: list[str] | None = None) -> GatewayListener:
    return GatewayListener(
        token="test-token",
        allowed_senders=allowed if allowed is not None else ["42"],
        project_dir=project_dir,
        send_replies=False,
    )


# ---------------------------------------------------------------------------
# unknown sender rejected, no row written
# ---------------------------------------------------------------------------

class TestUnknownSenderRejected:
    def test_unknown_sender_returns_unknown_sender(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=1001, sender_id=9999, text="/approve t-abc")

        result = listener.handle_update(update)

        assert result == "unknown_sender"

    def test_unknown_sender_writes_no_db_row(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=1002, sender_id=9999, text="/approve t-abc")

        listener.handle_update(update)

        conn = get_connection(project_dir)
        init_db(conn)
        row = operator_commands_dao.get_by_key(conn, "1002")
        conn.close()
        assert row is None, "No row must be written for unknown sender"


# ---------------------------------------------------------------------------
# telegram message_id deduplicates redelivery
# ---------------------------------------------------------------------------

class TestMessageIdDeduplication:
    def test_second_delivery_returns_duplicate(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=2001, sender_id=42, text="/close t-task1")

        with patch.object(listener, "_execute_command", return_value=({"message": "ok"}, "executed")):
            first = listener.handle_update(update)
            second = listener.handle_update(update)

        assert first == "ok:close"
        assert second == "duplicate"

    def test_duplicate_writes_no_second_row(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=2002, sender_id=42, text="/close t-task2")

        with patch.object(listener, "_execute_command", return_value=({"message": "ok"}, "executed")):
            listener.handle_update(update)
            listener.handle_update(update)

        conn = get_connection(project_dir)
        init_db(conn)
        rows = conn.execute(
            "SELECT COUNT(*) FROM operator_commands WHERE idempotency_key = '2002'"
        ).fetchone()[0]
        conn.close()
        assert rows == 1, "Exactly one row must exist after duplicate delivery"


# ---------------------------------------------------------------------------
# malformed command sends help reply
# ---------------------------------------------------------------------------

class TestMalformedCommandHelp:
    def test_unknown_command_returns_help(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        listener._send_replies = True  # enable reply capture
        update = _make_update(message_id=3001, sender_id=42, text="/bogus something")

        replies = []
        with patch.object(listener, "_send_reply", side_effect=lambda cid, txt: replies.append(txt)):
            result = listener.handle_update(update)

        assert result == "help"
        assert replies, "A reply must be sent for malformed commands"
        assert "approve" in replies[0].lower()

    def test_plain_text_returns_help(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=3002, sender_id=42, text="just some text")

        replies = []
        with patch.object(listener, "_send_reply", side_effect=lambda cid, txt: replies.append(txt)):
            result = listener.handle_update(update)

        assert result == "help"

    def test_command_without_task_id_returns_help(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=3003, sender_id=42, text="/approve")

        replies = []
        with patch.object(listener, "_send_reply", side_effect=lambda cid, txt: replies.append(txt)):
            result = listener.handle_update(update)

        assert result == "help"


# ---------------------------------------------------------------------------
# accepted command is recorded in DB
# ---------------------------------------------------------------------------

class TestCommandRecorded:
    def test_valid_command_writes_row(self, project_dir):
        listener = _make_listener(project_dir, allowed=["42"])
        update = _make_update(message_id=4001, sender_id=42, text="/reset t-foo")

        with patch.object(listener, "_execute_command", return_value=({"message": "done"}, "executed")):
            result = listener.handle_update(update)

        assert result == "ok:reset"
        conn = get_connection(project_dir)
        init_db(conn)
        row = operator_commands_dao.get_by_key(conn, "4001")
        conn.close()
        assert row is not None
        assert row.command == "reset"
        assert row.task_id == "t-foo"
        assert row.sender_id == "42"
        assert row.status == "executed"
