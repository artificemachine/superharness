"""Centralized logging for superharness.

One Logger per process. Honors SUPERHARNESS_LOG_LEVEL and
SUPERHARNESS_LOG_FILE env vars. Writes structured lines to a rotating
file (10 MB x 5). Audit channel is separate for security-sensitive ops.
"""
from __future__ import annotations

import logging
import os
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_LEVEL = "INFO"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUPS = 5

_FMT = "%(asctime)s %(levelname)s %(name)s:%(funcName)s:%(lineno)d %(message)s"
_DATEFMT = "%Y-%m-%dT%H:%M:%S%z"


def _default_log_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "superharness"
    if sys.platform.startswith("linux"):
        xdg = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        return Path(xdg) / "superharness"
    return Path.home() / ".superharness" / "logs"


def _resolve_log_file(env_var: str, default_name: str) -> Path:
    p = os.environ.get(env_var)
    if p:
        return Path(p).expanduser()
    return _default_log_dir() / default_name


def _ensure_handler(logger: logging.Logger, log_file: Path) -> None:
    """Attach a RotatingFileHandler if not already present for this file."""
    target = str(log_file.resolve())
    for h in logger.handlers:
        if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", None) == target:
            return
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        str(log_file), maxBytes=_DEFAULT_MAX_BYTES, backupCount=_DEFAULT_BACKUPS,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    logger.addHandler(handler)


def _resolve_level() -> int:
    raw = os.environ.get("SUPERHARNESS_LOG_LEVEL", _DEFAULT_LEVEL).upper().strip()
    return getattr(logging, raw, logging.INFO)


def get_logger(name: str = "superharness") -> logging.Logger:
    """Return a configured logger. Idempotent — repeated calls won't duplicate handlers."""
    if not name.startswith("superharness"):
        name = f"superharness.{name}"
    root = logging.getLogger("superharness")
    root.setLevel(_resolve_level())
    root.propagate = False
    _ensure_handler(root, _resolve_log_file("SUPERHARNESS_LOG_FILE", "superharness.log"))
    return logging.getLogger(name)


def get_audit_logger() -> logging.Logger:
    """Return the audit logger — security-sensitive ops only.

    Writes to a separate file so audit events can't be lost in app-log noise.
    Use for: launchctl load/unload, dispatch decisions, dangerous-flag uses,
    credential reads, plist writes.
    """
    audit = logging.getLogger("superharness.audit")
    audit.setLevel(logging.INFO)
    audit.propagate = False
    _ensure_handler(audit, _resolve_log_file("SUPERHARNESS_AUDIT_LOG_FILE", "superharness-audit.log"))
    return audit


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

_REDACTORS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_\-]+"), "sk-ant-***"),
    (re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"), "sk-***"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_***"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat_***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA***"),
    # Mask /Users/<name>/ → ~/  (drops home username)
    (re.compile(r"/Users/[^/\s]+"), "~"),
    (re.compile(r"/home/[^/\s]+"), "~"),
]


def redact(msg: str) -> str:
    """Mask common secret patterns and home paths in a log message."""
    if not isinstance(msg, str):
        return msg
    for pattern, repl in _REDACTORS:
        msg = pattern.sub(repl, msg)
    return msg
