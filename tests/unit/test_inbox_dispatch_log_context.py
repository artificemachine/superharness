"""Regression test: main()'s dispatch-failure log line must name its real
scope, not a copy-paste artifact from the nested argparse HelpFormatter
override defined earlier in the same function.

Found independently by 3 code-review passes (2026-07-22): the except block
guarding the real `dispatch(...)` call logged
`_log.warning("_format_usage: unexpected error: %s", ...)` — `_format_usage`
is `class _CapUsage(argparse.HelpFormatter): def _format_usage(...)`, an
unrelated nested method a few lines above, with nothing to do with a
dispatch failure. An operator debugging a real crash by grepping logs for
`_format_usage` would find nothing; grepping for `dispatch` (the thing that
actually failed) wouldn't match either. Whole point of this diff's own
logging pass was making failures traceable — a mislabeled one defeats it.
"""
from __future__ import annotations

import logging

import pytest


def test_dispatch_failure_log_names_dispatch_not_format_usage(monkeypatch, caplog, tmp_path):
    from superharness.commands import inbox_dispatch

    def _boom(**kwargs):
        raise RuntimeError("simulated dispatch failure")

    monkeypatch.setattr(inbox_dispatch, "dispatch", _boom)
    monkeypatch.setattr(inbox_dispatch, "_log_dispatch_error", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING):
        with pytest.raises(RuntimeError):
            inbox_dispatch.main(["--project", str(tmp_path)])

    messages = [r.message for r in caplog.records]
    assert not any("_format_usage" in m for m in messages), (
        "log context tag must not name the unrelated nested HelpFormatter method"
    )
    assert any("dispatch" in m.lower() for m in messages), (
        "log context tag should name the thing that actually failed"
    )
