"""Iteration 4 of PLAN-prime-agent-adoptions.md — telemetry payload hygiene.

Contract: no telemetry payload builder may embed a home path or username.
Project identity must go through `project_hash()`; task identity through
the sha256 pseudonym. This is the mechanical PII gate this repo has needed
6+ times (memory `feedback_audit_reports_releak_pii`).
"""

from __future__ import annotations

import inspect
import os
import re
import sys
import types
from pathlib import Path

import pytest


_HOME_LITERAL_RE = re.compile(
    r"['\"](?:/Users/|/home/|" + re.escape(str(Path.home())) + r")"
)


def test_no_hardcoded_home_path_literal_in_source():
    """Static check: no absolute home-path string literal in the module source."""
    from superharness.engine import langfuse_telemetry

    source = inspect.getsource(langfuse_telemetry)
    assert not _HOME_LITERAL_RE.search(source), (
        "langfuse_telemetry.py appears to embed a literal home-path prefix"
    )


class _FakeLangfuse:
    def __init__(self, **kwargs):
        self.events = []

    @classmethod
    def create_trace_id(cls, *, seed=None):
        return "a" * 32

    def create_event(self, **kwargs):
        self.events.append(kwargs)

    def flush(self):
        pass


@pytest.fixture(autouse=True)
def _isolated_langfuse_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SUPERHARNESS_CREDENTIALS_FILE", str(tmp_path / "credentials.env")
    )
    for name in (
        "SUPERHARNESS_LANGFUSE_ENABLED",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "LANGFUSE_TRACING_ENVIRONMENT",
        "DO_NOT_TRACK",
        "SUPERHARNESS_TELEMETRY",
        "SUPERHARNESS_STATE_PROJECT",
    ):
        monkeypatch.delenv(name, raising=False)


def test_no_home_path_or_username_in_payload_builders(tmp_path, monkeypatch):
    """Runtime check: a synthetic dispatch record whose project path lives
    under $HOME must never leak the home prefix or the OS username into the
    emitted payload — project identity goes through project_hash() only."""
    from superharness.engine import langfuse_telemetry

    monkeypatch.setenv("SUPERHARNESS_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.test")

    module = types.ModuleType("langfuse")
    module.Langfuse = _FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", module)
    monkeypatch.setattr(langfuse_telemetry, "_sdk_available", lambda: True)

    home = Path.home()
    username = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    project_dir = home / "DevOpsSec" / "a-private-project-name"

    record = {
        "task_id": "task-under-home",
        "agent": "codex-cli",
        "outcome": "done",
        "duration_seconds": 1.0,
        "cost_usd": 0.01,
        "model": "test-model",
        "slot_index": 0,
        "fanout_n": 1,
        "timestamp": "2026-08-10T00:00:00Z",
        "project_path": str(project_dir),
    }

    captured: dict[str, _FakeLangfuse] = {}

    def _fake_build(settings):
        client = _FakeLangfuse()
        captured["client"] = client
        return client

    monkeypatch.setattr(langfuse_telemetry, "_build_client", _fake_build)

    assert langfuse_telemetry.emit_dispatch_event(str(project_dir), record) is True

    payload = repr(captured["client"].events)
    assert str(home) not in payload, f"home path leaked into payload: {payload}"
    if username:
        assert username not in payload, f"username leaked into payload: {payload}"
