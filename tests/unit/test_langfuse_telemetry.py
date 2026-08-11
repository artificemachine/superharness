"""Privacy and failure-isolation tests for the optional Langfuse adapter."""

from __future__ import annotations

import sys
import types
from unittest.mock import ANY

import pytest


REQUIRED_ENV = {
    "SUPERHARNESS_LANGFUSE_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_TRACING_ENVIRONMENT",
    "SUPERHARNESS_STATE_PROJECT",
    # Iteration 4 of PLAN-prime-agent-adoptions.md: DO_NOT_TRACK/
    # SUPERHARNESS_TELEMETRY now gate LangfuseSettings.enabled too — clear
    # them so a CI runner (or a developer's shell) that happens to export
    # DO_NOT_TRACK=1 doesn't silently flip every test in this file to the
    # disabled branch. (Caught by the acceptance criterion in Iteration 4:
    # `DO_NOT_TRACK=1 uv run pytest tests/unit -q -k telemetry` must stay
    # green — an env leak must not break unrelated tests.)
    "DO_NOT_TRACK",
    "SUPERHARNESS_TELEMETRY",
}


@pytest.fixture(autouse=True)
def isolated_langfuse_environment(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SUPERHARNESS_CREDENTIALS_FILE", str(tmp_path / "credentials.env")
    )
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)


def _configure(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.test")
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "test")


class FakeLangfuse:
    instances = []
    trace_seeds = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.events = []
        self.flush_count = 0
        self.auth_result = True
        type(self).instances.append(self)

    @classmethod
    def create_trace_id(cls, *, seed=None):
        cls.trace_seeds.append(seed)
        return "a" * 32

    def create_event(self, **kwargs):
        self.events.append(kwargs)

    def flush(self):
        self.flush_count += 1

    def auth_check(self):
        return self.auth_result


@pytest.fixture
def fake_sdk(monkeypatch):
    from superharness.engine import langfuse_telemetry

    FakeLangfuse.instances = []
    FakeLangfuse.trace_seeds = []
    module = types.ModuleType("langfuse")
    module.Langfuse = FakeLangfuse
    monkeypatch.setitem(sys.modules, "langfuse", module)
    monkeypatch.setattr(langfuse_telemetry, "_sdk_available", lambda: True)
    return FakeLangfuse


def test_disabled_adapter_is_a_noop_without_client_construction(tmp_path, monkeypatch):
    from superharness.engine import langfuse_telemetry

    monkeypatch.setattr(
        langfuse_telemetry,
        "_build_client",
        lambda settings: pytest.fail("disabled telemetry constructed a client"),
    )

    assert langfuse_telemetry.emit_dispatch_event(str(tmp_path), {}) is False
    assert langfuse_telemetry.readiness() == ("disabled", "disabled")


def test_load_settings_preserves_file_first_precedence(tmp_path, monkeypatch):
    from superharness.engine.langfuse_telemetry import load_settings

    path = tmp_path / "credentials.env"
    path.write_text(
        "SUPERHARNESS_LANGFUSE_ENABLED=true\n"
        "LANGFUSE_PUBLIC_KEY=file-public\n"
        "LANGFUSE_SECRET_KEY=file-secret\n"
        "LANGFUSE_BASE_URL=https://file.example.test\n"
        "LANGFUSE_TRACING_ENVIRONMENT=file-env\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("SUPERHARNESS_CREDENTIALS_FILE", str(path))
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "environment-public")

    settings = load_settings()

    assert settings.enabled is True
    assert settings.public_key == "file-public"
    assert settings.secret_key == "file-secret"
    assert settings.base_url == "https://file.example.test"
    assert settings.environment == "file-env"
    assert settings.timeout_seconds == 2


def test_readiness_reports_incomplete_and_missing_sdk(monkeypatch):
    from superharness.engine import langfuse_telemetry

    monkeypatch.setenv("SUPERHARNESS_LANGFUSE_ENABLED", "yes")
    assert langfuse_telemetry.readiness() == (
        "incomplete",
        "missing LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL",
    )

    _configure(monkeypatch)
    monkeypatch.setattr(langfuse_telemetry, "_sdk_available", lambda: False)
    assert langfuse_telemetry.readiness() == (
        "missing-sdk",
        "install superharness[observability]",
    )


def test_emit_dispatch_event_uses_exact_privacy_allowlist(
    tmp_path, monkeypatch, fake_sdk
):
    from superharness import __version__
    from superharness.engine.langfuse_telemetry import emit_dispatch_event

    _configure(monkeypatch)
    record = {
        "task_id": "private-task-name",
        "agent": "codex-cli",
        "outcome": "done",
        "duration_seconds": 12.5,
        "cost_usd": 0.125,
        "model": "test-model",
        "slot_index": 2,
        "fanout_n": 3,
        "timestamp": "2026-08-06T10:00:00Z",
        "prompt": "must-not-leave",
        "output": "must-not-leave",
        "project_path": str(tmp_path),
    }

    assert emit_dispatch_event(str(tmp_path), record) is True

    client = fake_sdk.instances[0]
    assert client.kwargs == {
        "public_key": "test-public-key",
        "secret_key": "test-secret-key",
        "base_url": "https://langfuse.example.test",
        "environment": "test",
        "timeout": 2,
        "release": __version__,
    }
    assert client.flush_count == 1
    assert client.events == [
        {
            "name": "superharness.dispatch.completed",
            "trace_context": {"trace_id": "a" * 32},
            "metadata": {
                "project_id": ANY,
                "task_id_hash": ANY,
                "agent": "codex-cli",
                "outcome": "done",
                "duration_seconds": 12.5,
                "cost_usd": 0.125,
                "model": "test-model",
                "slot_index": 2,
                "fanout_n": 3,
                "timestamp": "2026-08-06T10:00:00Z",
                "superharness_version": __version__,
            },
            "level": "DEFAULT",
            "status_message": "done",
        }
    ]
    metadata = client.events[0]["metadata"]
    assert set(metadata) == {
        "project_id",
        "task_id_hash",
        "agent",
        "outcome",
        "duration_seconds",
        "cost_usd",
        "model",
        "slot_index",
        "fanout_n",
        "timestamp",
        "superharness_version",
    }
    assert "private-task-name" not in str(metadata)
    assert str(tmp_path) not in str(metadata)
    assert "must-not-leave" not in str(metadata)


def test_trace_seed_groups_state_project_and_task_without_exporting_them(
    tmp_path, monkeypatch, fake_sdk
):
    from superharness.engine.langfuse_telemetry import emit_dispatch_event

    _configure(monkeypatch)
    state_project = tmp_path / "canonical"
    monkeypatch.setenv("SUPERHARNESS_STATE_PROJECT", str(state_project))
    record = {"task_id": "task-42", "outcome": "failed"}

    assert emit_dispatch_event(str(tmp_path / "worktree-a"), record) is True
    assert emit_dispatch_event(str(tmp_path / "worktree-b"), record) is True

    assert fake_sdk.trace_seeds[0] == fake_sdk.trace_seeds[1]
    first_event = fake_sdk.instances[0].events[0]
    assert first_event["level"] == "ERROR"
    assert str(state_project) not in str(first_event)
    assert "task-42" not in str(first_event)


def test_probe_auth_uses_configured_client(monkeypatch, fake_sdk):
    from superharness.engine.langfuse_telemetry import probe_auth

    _configure(monkeypatch)
    assert probe_auth() is True
    assert len(fake_sdk.instances) == 1


@pytest.mark.parametrize("failure_point", ["construct", "event", "flush", "auth"])
def test_sdk_failures_are_redacted_and_non_fatal(
    tmp_path, monkeypatch, caplog, fake_sdk, failure_point
):
    from superharness.engine import langfuse_telemetry

    _configure(monkeypatch)

    if failure_point == "construct":
        fake_sdk.__init__ = lambda self, **kwargs: (_ for _ in ()).throw(
            RuntimeError("test-secret-key")
        )
    elif failure_point == "event":
        fake_sdk.create_event = lambda self, **kwargs: (_ for _ in ()).throw(
            RuntimeError("test-secret-key")
        )
    elif failure_point == "flush":
        fake_sdk.flush = lambda self: (_ for _ in ()).throw(
            RuntimeError("test-secret-key")
        )
    else:
        fake_sdk.auth_check = lambda self: (_ for _ in ()).throw(
            RuntimeError("test-secret-key")
        )

    if failure_point == "auth":
        assert langfuse_telemetry.probe_auth() is False
    else:
        assert (
            langfuse_telemetry.emit_dispatch_event(
                str(tmp_path), {"task_id": "task", "outcome": "failed"}
            )
            is False
        )

    assert "test-secret-key" not in caplog.text
    assert "RuntimeError" in caplog.text
