"""Telegram gateway listener — receives operator commands via long-polling.

Supported commands:
  /approve <task_id>   — approve a task's pending plan
  /reject  <task_id>   — reject a task's pending plan
  /close   <task_id>   — mark a task done
  /reset   <task_id>   — reset a task to todo

Security model:
  - Only chat_ids / user_ids listed in allowed_senders are processed.
  - Every update is keyed by Telegram message_id; duplicate deliveries are
    detected via operator_commands_dao and silently skipped.
  - Malformed or unknown commands receive a help reply.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from superharness.guard.redact import TokenRedactingFilter, redact_bot_token

logger = logging.getLogger(__name__)
logger.addFilter(TokenRedactingFilter())

# Re-exported so this module's own call sites (and callers) can redact an
# arbitrary string without a logger in the loop.
_redact_token = redact_bot_token

HELP_TEXT = (
    "Superharness operator commands:\n"
    "  /approve <task_id>  — approve a pending plan\n"
    "  /reject  <task_id>  — reject a pending plan\n"
    "  /close   <task_id>  — mark task done\n"
    "  /reset   <task_id>  — reset task to todo\n"
)

KNOWN_COMMANDS = frozenset(["approve", "reject", "close", "reset"])


@dataclass(frozen=True)
class ParsedCommand:
    command: str
    task_id: str


def parse_command(text: str) -> ParsedCommand | None:
    """Parse a Telegram message text into a ParsedCommand.

    Accepts both '/approve t-abc' and '/approve@botname t-abc' forms.
    Returns None if the message is not a recognised command or is malformed.
    """
    if not text:
        return None
    text = text.strip()
    if not text.startswith("/"):
        return None

    # Strip leading slash and optional @botname suffix on the command word
    parts = text[1:].split(None, 1)
    if not parts:
        return None

    cmd_word = parts[0].split("@", 1)[0].lower()
    if cmd_word not in KNOWN_COMMANDS:
        return None

    if len(parts) < 2 or not parts[1].strip():
        # Command recognised but task_id missing — treat as malformed
        return None

    task_id = parts[1].strip()
    return ParsedCommand(command=cmd_word, task_id=task_id)


def validate_sender(sender_id: str, allowed_senders: list[str]) -> bool:
    """Return True iff sender_id appears in the allowed_senders list."""
    return str(sender_id) in [str(s) for s in allowed_senders]


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class GatewayListener:
    """Long-poll Telegram and process operator commands."""

    def __init__(
        self,
        token: str,
        allowed_senders: list[str],
        project_dir: str,
        *,
        send_replies: bool = True,
    ) -> None:
        self._token = token
        self._allowed_senders = [str(s) for s in allowed_senders]
        self._project_dir = project_dir
        self._send_replies = send_replies
        self._base_url = f"https://api.telegram.org/bot{token}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, poll_timeout_s: int = 30, sleep_on_error_s: float = 5.0) -> None:
        """Block and process updates forever. Call from a daemon thread/process."""
        offset: int = 0
        logger.info("Telegram gateway listener started (project=%s)", self._project_dir)
        while True:
            try:
                updates = self._get_updates(offset, timeout=poll_timeout_s)
                for update in updates:
                    update_id: int = update["update_id"]
                    self._handle_update(update)
                    offset = update_id + 1
            except Exception as e:
                logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
                logger.exception("Error in gateway poll loop; sleeping %ss", sleep_on_error_s)
                time.sleep(sleep_on_error_s)

    def handle_update(self, update: dict[str, Any]) -> str:
        """Process one Telegram update dict. Returns a status string for testing.

        Possible return values:
          "duplicate"        — message_id already seen; skipped
          "unknown_sender"   — sender not in allowlist; rejected (no DB row)
          "help"             — command was malformed; help reply sent
          "ok:<command>"     — command accepted and executed
        """
        return self._handle_update(update)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _handle_update(self, update: dict[str, Any]) -> str:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return "no_message"

        message_id: int = message["message_id"]
        idempotency_key = str(message_id)
        chat_id: int = message["chat"]["id"]
        sender_id = str(message.get("from", {}).get("id", ""))
        text: str = message.get("text", "") or ""

        # 1. Sender validation — BEFORE any DB write
        if not validate_sender(sender_id, self._allowed_senders):
            logger.warning(
                "Gateway: unknown sender %s (message_id=%s) rejected",
                sender_id, message_id,
            )
            return "unknown_sender"

        # 2. Deduplication check
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import operator_commands_dao
            conn = get_connection(self._project_dir)
            try:
                init_db(conn)
                if operator_commands_dao.is_duplicate(conn, idempotency_key):
                    logger.debug("Gateway: duplicate message_id=%s skipped", message_id)
                    conn.close()
                    return "duplicate"
                conn.close()
            except Exception as e:
                logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
                conn.close()
                raise
        except Exception as e:
            logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
            logger.exception("Gateway: DB check failed for message_id=%s", message_id)
            return "error"

        # 3. Parse the command
        parsed = parse_command(text)
        if parsed is None:
            logger.info("Gateway: malformed command from %s: %r", sender_id, text)
            self._send_reply(chat_id, HELP_TEXT)
            return "help"

        # 4. Record in DB (dedup slot claimed)
        now = _now_utc()
        try:
            conn = get_connection(self._project_dir)
            try:
                init_db(conn)
                row, is_new = operator_commands_dao.insert(
                    conn,
                    idempotency_key=idempotency_key,
                    command=parsed.command,
                    task_id=parsed.task_id,
                    sender_id=sender_id,
                    now=now,
                )
                conn.commit()
                if not is_new:
                    conn.close()
                    return "duplicate"
                row_id = row.id
                conn.close()
            except Exception as e:
                logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
                conn.close()
                raise
        except Exception as e:
            logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
            logger.exception("Gateway: DB insert failed for message_id=%s", message_id)
            return "error"

        # 5. Execute the command
        result, status = self._execute_command(parsed, sender_id)

        # 6. Persist result
        try:
            conn = get_connection(self._project_dir)
            try:
                init_db(conn)
                operator_commands_dao.update_status(
                    conn, row_id, status=status, result=result, now=_now_utc()
                )
                conn.commit()
                conn.close()
            except Exception as e:
                logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
                conn.close()
        except Exception as e:
            logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
            logger.exception("Gateway: failed to update command status for message_id=%s", message_id)

        # 7. Reply
        reply = result.get("message", f"Command {parsed.command} executed.")
        self._send_reply(chat_id, reply)
        return f"ok:{parsed.command}"

    def _execute_command(
        self, parsed: ParsedCommand, sender_id: str
    ) -> tuple[dict[str, Any], str]:
        """Dispatch the parsed command to the superharness state engine."""
        _COMMAND_STATUS: dict[str, tuple[str, str | None]] = {
            "approve": ("plan_approved", "plan_approved_at"),
            "reject":  ("stopped",       "stopped_at"),
            "close":   ("done",          "done_at"),
            # "todo", not "pending": "pending" is the initial status of a
            # decomposed subtask (commands/delegate.py), not an entry point in
            # the task lifecycle — no lifecycle rule advances a task sitting at
            # it, so /reset used to strand the task invisibly.
            "reset":   ("todo",          None),
        }
        target_status, ts_field = _COMMAND_STATUS.get(parsed.command, (None, None))
        if target_status is None:
            return {"message": f"Unknown command: {parsed.command}"}, "failed"

        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import tasks_dao
            conn = get_connection(self._project_dir)
            try:
                init_db(conn)
                task = tasks_dao.get(conn, parsed.task_id)
                if task is None:
                    conn.close()
                    return {"message": f"Task {parsed.task_id!r} not found."}, "failed"

                now = _now_utc()
                changes: dict[str, Any] = {"status": target_status, "updated_at": now}
                if ts_field:
                    changes[ts_field] = now
                tasks_dao.update(conn, parsed.task_id, task.version, changes)
                conn.commit()
                conn.close()
                return {"message": f"Task {parsed.task_id} {parsed.command}d."}, "executed"
            except Exception as e:
                logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
                conn.close()
                raise
        except Exception as exc:
            logger.exception("Gateway: command execution failed")
            return {"message": f"Execution error: {exc}"}, "failed"

    def _get_updates(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
        try:
            import requests
        except ImportError:
            logger.error("requests library not available; cannot poll Telegram")
            time.sleep(timeout)
            return []

        url = f"{self._base_url}/getUpdates"
        params: dict[str, Any] = {"timeout": timeout, "offset": offset}
        try:
            resp = requests.get(url, params=params, timeout=timeout + 5)
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
            logger.warning("getUpdates returned not-ok: %s", data)
            return []
        except Exception as e:
            logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
            logger.exception("getUpdates failed")
            return []

    def _send_reply(self, chat_id: int, text: str) -> None:
        if not self._send_replies:
            return
        try:
            import requests
        except ImportError:
            return
        url = f"{self._base_url}/sendMessage"
        try:
            requests.post(
                url,
                json={"chat_id": chat_id, "text": text},
                timeout=10,
            )
        except Exception as e:
            logger.warning("telegram_gateway.py unexpected error: %s", e, exc_info=True)
            logger.exception("sendMessage failed (chat_id=%s)", chat_id)
