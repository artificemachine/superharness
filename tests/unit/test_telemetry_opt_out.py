"""Iteration 4 of PLAN-prime-agent-adoptions.md — telemetry opt-out.

`DO_NOT_TRACK=1` (or `SUPERHARNESS_TELEMETRY=0/false/no/off`) disables
Langfuse telemetry at the single settings choke point
(`LangfuseSettings.enabled`, resolved by `load_settings()`). `DO_NOT_TRACK`
takes precedence over an explicit enable — the opt-out is absolute,
mirroring prime-agent's precedence (see plan section 3, Iteration 4).
"""

from __future__ import annotations

import pytest


REQUIRED_ENV = {
    "SUPERHARNESS_LANGFUSE_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_TRACING_ENVIRONMENT",
    "DO_NOT_TRACK",
    "SUPERHARNESS_TELEMETRY",
}


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "SUPERHARNESS_CREDENTIALS_FILE", str(tmp_path / "credentials.env")
    )
    for name in REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)


def _configure_credentials(monkeypatch):
    monkeypatch.setenv("SUPERHARNESS_LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public-key")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.test")


def test_do_not_track_disables_telemetry(monkeypatch):
    from superharness.engine.langfuse_telemetry import load_settings

    _configure_credentials(monkeypatch)
    monkeypatch.setenv("DO_NOT_TRACK", "1")

    assert load_settings().enabled is False


def test_superharness_telemetry_zero_disables(monkeypatch):
    from superharness.engine.langfuse_telemetry import load_settings

    _configure_credentials(monkeypatch)
    monkeypatch.setenv("SUPERHARNESS_TELEMETRY", "0")

    assert load_settings().enabled is False


def test_explicit_enable_does_not_override_do_not_track(monkeypatch):
    from superharness.engine.langfuse_telemetry import load_settings

    _configure_credentials(monkeypatch)
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    monkeypatch.setenv("SUPERHARNESS_TELEMETRY", "1")

    assert load_settings().enabled is False


def test_default_unchanged_without_env(monkeypatch):
    from superharness.engine.langfuse_telemetry import load_settings

    _configure_credentials(monkeypatch)

    assert load_settings().enabled is True


def test_garbage_do_not_track_ignored(monkeypatch):
    """DO_NOT_TRACK=garbage is treated as unset, not truthy."""
    from superharness.engine.langfuse_telemetry import load_settings

    _configure_credentials(monkeypatch)
    monkeypatch.setenv("DO_NOT_TRACK", "garbage")

    assert load_settings().enabled is True
