"""TDD tests for src/superharness/logging_utils.py — centralized logging.

Spec:
- get_logger(name) returns a stdlib Logger configured once per process
- Honors SUPERHARNESS_LOG_LEVEL env var (default INFO)
- Honors SUPERHARNESS_LOG_FILE env var (default platform-appropriate path)
- Format includes timestamp, level, module:func:lineno, message
- RotatingFileHandler with 10 MB cap, 5 backups
- get_audit_logger() writes to a separate file (security-sensitive ops)
- redact() masks secrets in log messages (tokens, long /Users paths)
"""
from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")
sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def isolate_logging(tmp_path, monkeypatch):
    """Each test gets a clean log dir + fresh logger registry."""
    monkeypatch.setenv("SUPERHARNESS_LOG_FILE", str(tmp_path / "sh.log"))
    monkeypatch.setenv("SUPERHARNESS_AUDIT_LOG_FILE", str(tmp_path / "sh-audit.log"))
    monkeypatch.setenv("SUPERHARNESS_LOG_LEVEL", "DEBUG")
    # Reload the module each test so handler attachments don't leak
    if "superharness.logging_utils" in sys.modules:
        # Detach handlers from any existing loggers so they release file handles
        for name in ("superharness", "superharness.audit"):
            lg = logging.getLogger(name)
            for h in list(lg.handlers):
                lg.removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        del sys.modules["superharness.logging_utils"]
    yield


def test_get_logger_returns_logger_instance():
    from superharness.logging_utils import get_logger
    log = get_logger("superharness.test")
    assert isinstance(log, logging.Logger)


def test_get_logger_writes_to_log_file(tmp_path):
    from superharness.logging_utils import get_logger
    log = get_logger("superharness.test_write")
    log.info("hello world")
    for h in log.handlers + logging.getLogger("superharness").handlers:
        h.flush()
    log_file = Path(os.environ["SUPERHARNESS_LOG_FILE"])
    assert log_file.is_file(), f"log file not created: {log_file}"
    content = log_file.read_text()
    assert "hello world" in content
    assert "INFO" in content
    assert "superharness.test_write" in content


def test_log_format_includes_module_func_lineno():
    from superharness.logging_utils import get_logger
    log = get_logger("superharness.test_fmt")
    log.warning("formatted")
    for h in logging.getLogger("superharness").handlers:
        h.flush()
    content = Path(os.environ["SUPERHARNESS_LOG_FILE"]).read_text()
    # Format: "<ts> <level> <module>:<func>:<lineno> <message>"
    pattern = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\S* WARNING superharness\.test_fmt:[\w_]+:\d+ formatted"
    assert re.search(pattern, content), (
        f"log format does not match expected pattern.\nGot:\n{content}"
    )


def test_log_level_honors_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("SUPERHARNESS_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("SUPERHARNESS_LOG_FILE", str(tmp_path / "lvl.log"))
    if "superharness.logging_utils" in sys.modules:
        del sys.modules["superharness.logging_utils"]
    from superharness.logging_utils import get_logger
    log = get_logger("superharness.test_lvl")
    log.debug("debug-not-shown")
    log.warning("warn-shown")
    for h in logging.getLogger("superharness").handlers:
        h.flush()
    content = (tmp_path / "lvl.log").read_text()
    assert "debug-not-shown" not in content
    assert "warn-shown" in content


def test_audit_logger_writes_to_separate_file():
    from superharness.logging_utils import get_audit_logger
    audit = get_audit_logger()
    audit.info("launchctl load com.superharness.inbox.test")
    for h in audit.handlers + logging.getLogger("superharness.audit").handlers:
        h.flush()
    audit_file = Path(os.environ["SUPERHARNESS_AUDIT_LOG_FILE"])
    main_file = Path(os.environ["SUPERHARNESS_LOG_FILE"])
    assert audit_file.is_file()
    assert "launchctl load" in audit_file.read_text()
    # Audit msg must not bleed into main log
    if main_file.is_file():
        assert "launchctl load" not in main_file.read_text()


def test_rotating_handler_caps_size(tmp_path, monkeypatch):
    """Logger uses RotatingFileHandler — verify maxBytes set."""
    from superharness.logging_utils import get_logger
    from logging.handlers import RotatingFileHandler
    log = get_logger("superharness.test_rotate")
    file_handlers = [
        h for h in logging.getLogger("superharness").handlers
        if isinstance(h, RotatingFileHandler)
    ]
    assert file_handlers, "must use RotatingFileHandler"
    h = file_handlers[0]
    assert h.maxBytes >= 1_000_000, f"maxBytes too small: {h.maxBytes}"
    assert h.backupCount >= 3, f"backupCount too small: {h.backupCount}"


def test_redact_masks_anthropic_api_key():
    from superharness.logging_utils import redact
    msg = "Calling API with key sk-ant-api03-AAAA-BBBB-CCCC"
    out = redact(msg)
    assert "sk-ant-api03-AAAA-BBBB-CCCC" not in out
    assert "sk-ant-***" in out or "***" in out


def test_redact_masks_user_home_path():
    from superharness.logging_utils import redact
    msg = "wrote file /Users/testuser/secret/file.txt"
    out = redact(msg)
    # Either masked or stripped to ~/
    assert "testuser" not in out


def test_get_logger_idempotent():
    """Calling get_logger twice with same name must NOT add duplicate handlers."""
    from superharness.logging_utils import get_logger
    a = get_logger("superharness.idem")
    a_handlers = len(logging.getLogger("superharness").handlers)
    b = get_logger("superharness.idem")
    b_handlers = len(logging.getLogger("superharness").handlers)
    assert a is b or a.name == b.name
    assert a_handlers == b_handlers, (
        "duplicate handler attached on second get_logger call"
    )
