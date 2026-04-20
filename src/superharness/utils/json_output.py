"""Shared JSON output helper for CLI commands.

Commands that support --json should route both success and failure paths
through emit_json() so the caller gets a single well-formed JSON object on
stdout and a deterministic exit code.

Contract:
- stdout: exactly one JSON object, terminated by newline.
- stderr: untouched (callers may still log diagnostics there).
- exit code: 0 on success, 1 (or caller-chosen) on error.
- Success payloads include ``"ok": true``.
- Error payloads include ``"ok": false`` and ``"error": "<message>"``.

Callers MUST NOT also print human output when --json is set, since that would
pollute stdout.
"""
from __future__ import annotations

import json
import sys
from typing import Any


def emit_json(
    payload: dict[str, Any],
    *,
    ok: bool = True,
    exit_code: int | None = None,
) -> None:
    """Print payload as JSON to stdout and exit with exit_code.

    If exit_code is None, exits 0 when ok=True else 1.
    """
    out = dict(payload)
    out.setdefault("ok", bool(ok))
    # Always write to the real stdout (sys.__stdout__), not whatever the
    # caller may have redirected — emit_json must produce deterministic
    # machine-readable output regardless of surrounding capture logic.
    target = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout
    target.write(json.dumps(out, default=str))
    target.write("\n")
    target.flush()
    if exit_code is None:
        exit_code = 0 if ok else 1
    sys.exit(exit_code)


def emit_error(message: str, *, exit_code: int = 1, **extra: Any) -> None:
    """Shortcut: emit a {'ok': false, 'error': ...} payload and exit."""
    payload: dict[str, Any] = {"error": message}
    payload.update(extra)
    emit_json(payload, ok=False, exit_code=exit_code)
