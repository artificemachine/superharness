"""Optional, privacy-first Langfuse telemetry for dispatch outcomes.

The adapter is deliberately failure-isolated: local Superharness state remains
authoritative, and missing configuration, an absent optional SDK, or any SDK
failure turns telemetry into a no-op.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from superharness import __version__
from superharness.engine.credentials import read_credentials_file
from superharness.utils.paths import project_hash, resolve_state_project_path

logger = logging.getLogger(__name__)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_REQUIRED_SETTINGS = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
)


@dataclass(frozen=True)
class LangfuseSettings:
    """Resolved Langfuse configuration without any repository-local secrets."""

    enabled: bool
    public_key: str
    secret_key: str
    base_url: str
    environment: str = "default"
    timeout_seconds: int = 2


def _value(values: Mapping[str, str], name: str, default: str = "") -> str:
    """Preserve the existing credential-file-first precedence contract."""
    return values.get(name, os.environ.get(name, default))


def load_settings() -> LangfuseSettings:
    """Load Langfuse settings from the machine credential store and env."""
    values = read_credentials_file()
    enabled = _value(values, "SUPERHARNESS_LANGFUSE_ENABLED").lower()
    return LangfuseSettings(
        enabled=enabled in _TRUE_VALUES,
        public_key=_value(values, "LANGFUSE_PUBLIC_KEY"),
        secret_key=_value(values, "LANGFUSE_SECRET_KEY"),
        base_url=_value(values, "LANGFUSE_BASE_URL"),
        environment=_value(values, "LANGFUSE_TRACING_ENVIRONMENT", "default"),
    )


def _sdk_available() -> bool:
    """Return whether the optional SDK can be imported without importing it."""
    try:
        return importlib.util.find_spec("langfuse") is not None
    except (ImportError, ValueError):
        return "langfuse" in sys.modules


def readiness(settings: LangfuseSettings | None = None) -> tuple[str, str]:
    """Return a stable machine-readable readiness state and safe detail."""
    resolved = settings or load_settings()
    if not resolved.enabled:
        return "disabled", "disabled"

    configured = {
        "LANGFUSE_PUBLIC_KEY": resolved.public_key,
        "LANGFUSE_SECRET_KEY": resolved.secret_key,
        "LANGFUSE_BASE_URL": resolved.base_url,
    }
    missing = [name for name in _REQUIRED_SETTINGS if not configured[name]]
    if missing:
        return "incomplete", f"missing {', '.join(missing)}"
    if not _sdk_available():
        return "missing-sdk", "install superharness[observability]"
    return "configured", resolved.base_url


def _build_client(settings: LangfuseSettings) -> Any:
    """Construct the SDK client only after readiness has succeeded."""
    from langfuse import Langfuse

    return Langfuse(
        public_key=settings.public_key,
        secret_key=settings.secret_key,
        base_url=settings.base_url,
        environment=settings.environment,
        timeout=settings.timeout_seconds,
        release=__version__,
    )


def _log_failure(operation: str, exc: BaseException) -> None:
    """Log only the exception class because messages may echo credentials."""
    logger.warning("langfuse %s failed (%s)", operation, type(exc).__name__)


def probe_auth(settings: LangfuseSettings | None = None) -> bool:
    """Perform the explicit blocking credential probe requested by an operator."""
    resolved = settings or load_settings()
    if readiness(resolved)[0] != "configured":
        return False
    try:
        return bool(_build_client(resolved).auth_check())
    except Exception as exc:
        _log_failure("authentication", exc)
        return False


def _pseudonym(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def emit_dispatch_event(project_dir: str, record: Mapping[str, Any]) -> bool:
    """Export one completed dispatch event without exposing task content."""
    settings = load_settings()
    if readiness(settings)[0] != "configured":
        return False

    try:
        client = _build_client(settings)
        task_id = str(record.get("task_id", ""))
        state_project = resolve_state_project_path(project_dir)
        project_id = project_hash(state_project)
        trace_id = client.create_trace_id(seed=f"{project_id}:{task_id}")
        outcome = str(record.get("outcome", ""))
        metadata = {
            "project_id": project_id,
            "task_id_hash": _pseudonym(task_id),
            "agent": record.get("agent", ""),
            "outcome": outcome,
            "duration_seconds": record.get("duration_seconds", 0.0),
            "cost_usd": record.get("cost_usd", 0.0),
            "model": record.get("model", ""),
            "slot_index": record.get("slot_index", -1),
            "fanout_n": record.get("fanout_n", 1),
            "timestamp": record.get("timestamp", ""),
            "superharness_version": __version__,
        }
        client.create_event(
            name="superharness.dispatch.completed",
            trace_context={"trace_id": trace_id},
            metadata=metadata,
            level="ERROR" if outcome in {"failed", "timeout"} else "DEFAULT",
            status_message=outcome,
        )
        client.flush()
        return True
    except Exception as exc:
        _log_failure("dispatch export", exc)
        return False
