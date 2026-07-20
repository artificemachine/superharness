"""Credential redaction — strip secrets before persisting to disk.

Cherry-picked from hermes-agent/agent/redact.py.
"""
import logging
import re

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'sk-[a-zA-Z0-9_-]{6,}'), "[REDACTED_API_KEY]"),
    (re.compile(r'sk-proj-[a-zA-Z0-9_-]{6,}'), "[REDACTED_API_KEY]"),
    (re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{20,}'), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r'(?:password|passwd|pwd)\s*[=:]\s*\S+', re.IGNORECASE), "[REDACTED_PASSWORD]"),
    (re.compile(r'[a-zA-Z0-9_-]+://[^:]+:([^@]+)@'), r'[REDACTED_PASSWORD]@'),
    (re.compile(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----\n.*?\n-----END [A-Z ]+ PRIVATE KEY-----', re.DOTALL), "[REDACTED_KEY]"),
    (re.compile(r'\d{6,10}:[A-Za-z0-9_-]{10,}'), "[REDACTED_TOKEN]"),
    (re.compile(r'AKIA[A-Z0-9]{16}'), "[REDACTED_KEY]"),
    (re.compile(r'ghp_[A-Za-z0-9]{15,}'), "[REDACTED_TOKEN]"),
    (re.compile(r'(?:api_key|apikey|api-secret)\s*[=:]\s*\S+', re.IGNORECASE), "[REDACTED_KEY]"),
]


def redact(text: str) -> str:
    """Scan text for secrets and replace with redaction markers.

    Returns the text with all detected secrets replaced by [REDACTED_*] markers.
    Safe text (no secrets) is returned unchanged.
    """
    if not text:
        return text
    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    return result


# ---------------------------------------------------------------------------
# Telegram bot-token URL redaction
#
# Telegram API URLs embed the bot token directly in the path segment:
# https://api.telegram.org/bot<token>/getUpdates. `requests` exceptions
# stringify the full URL, so any logger call that carries such an exception
# (directly, or via exc_info=True) discloses the token. This targets that
# specific shape and preserves the rest of the URL, unlike the generic
# `redact()` above (which only matches longer, path-free token strings and
# replaces the whole match with an opaque marker).
# ---------------------------------------------------------------------------

_BOT_TOKEN_PATTERN = re.compile(r"(bot)\d{3,}:[A-Za-z0-9_-]+")


def redact_bot_token(text: str) -> str:
    """Mask a Telegram `bot<id>:<secret>` token embedded in a URL or message.

    Returns text unchanged (no-op) when no such token shape is present.
    """
    if not text:
        return text
    return _BOT_TOKEN_PATTERN.sub(r"\1<redacted>", text)


class TokenRedactingFilter(logging.Filter):
    """Logging filter that redacts Telegram bot tokens from every record.

    Mutates `record.msg`/`record.args` (collapsing them to the already
    formatted, redacted message) and, when the record carries `exc_info`,
    pre-renders the traceback through the redactor and clears `exc_info` so
    the formatter does not re-render the raw (unredacted) traceback.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            message = str(record.msg)
        record.msg = redact_bot_token(message)
        record.args = ()

        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact_bot_token(formatted)
            record.exc_info = None
        elif getattr(record, "exc_text", None):
            record.exc_text = redact_bot_token(record.exc_text)

        return True
