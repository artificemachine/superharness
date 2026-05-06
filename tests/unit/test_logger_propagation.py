"""Verify that any module using `logging.getLogger(__name__)` flows
to the central rotating file handler — no per-module migration needed.

This is the cheap way to get every `superharness.*` module logging
without touching 44 files."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
SRC = str(REPO_ROOT / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_LOG_FILE", str(tmp_path / "main.log"))
    monkeypatch.setenv("SUPERHARNESS_AUDIT_LOG_FILE", str(tmp_path / "audit.log"))
    monkeypatch.setenv("SUPERHARNESS_LOG_LEVEL", "DEBUG")
    for name in ("superharness", "superharness.audit"):
        lg = logging.getLogger(name)
        for h in list(lg.handlers):
            lg.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
    if "superharness.logging_utils" in sys.modules:
        del sys.modules["superharness.logging_utils"]
    yield


def test_submodule_log_flows_to_central_file_after_bootstrap():
    """When the central logger is bootstrapped, any submodule that uses
    `logging.getLogger(__name__)` writes to the central log file via
    propagation up the logger hierarchy."""
    from superharness.logging_utils import get_logger
    get_logger("superharness")  # bootstrap

    submod_log = logging.getLogger("superharness.commands.somefoo")
    submod_log.setLevel(logging.DEBUG)
    submod_log.warning("propagated submodule message")

    for h in logging.getLogger("superharness").handlers:
        h.flush()
    content = Path(os.environ["SUPERHARNESS_LOG_FILE"]).read_text()
    assert "propagated submodule message" in content
    assert "superharness.commands.somefoo" in content


def test_audit_logger_does_not_flood_main_log():
    """Audit messages must remain on the audit channel only."""
    from superharness.logging_utils import get_logger, get_audit_logger
    get_logger("superharness")  # bootstrap main
    audit = get_audit_logger()
    audit.info("sensitive op: launchctl load com.test.plist")

    for h in logging.getLogger("superharness").handlers + logging.getLogger("superharness.audit").handlers:
        h.flush()

    main_content = Path(os.environ["SUPERHARNESS_LOG_FILE"]).read_text() \
        if Path(os.environ["SUPERHARNESS_LOG_FILE"]).is_file() else ""
    audit_content = Path(os.environ["SUPERHARNESS_AUDIT_LOG_FILE"]).read_text()

    assert "sensitive op" in audit_content
    assert "sensitive op" not in main_content
