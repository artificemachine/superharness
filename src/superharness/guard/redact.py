"""Credential redaction — strip secrets before persisting to disk.

Cherry-picked from hermes-agent/agent/redact.py.
"""
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
