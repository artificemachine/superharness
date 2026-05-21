"""Summarizer adapter for observation snapshots.

Provider-agnostic interface that turns a task context dict into a short
summary string. Selection happens via an explicit name, the
SUPERHARNESS_SUMMARIZER env var, or a "noop" fallback. The Noop default
is deterministic and network-free so the auto-capture loop ships
without external calls.

External providers (Anthropic, Gemini, OpenAI, OpenRouter, OpenCode)
live in `summarizer_providers` and self-register at import time.
They are auto-loaded at the bottom of this module so callers only
need to import from here.

Rate limiting is applied per process when a provider's
`SummarizerConfig.max_per_hour` is set. The wrap is transparent: the
returned object still satisfies the `Summarizer` protocol. The limit
is overridden by `SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR` if set. The
bucket is in-memory and per-process; multiple `shux` processes have
independent buckets. Cross-process limiting is future work.

Calls into a rate-limited summarizer that exceed the bucket raise
`RateLimitExceeded`. The auto-capture caller in
`engine.observation_capture` catches every exception and returns
None, so a rate-limit hit silently skips that snapshot without
breaking the lifecycle transition.
"""
from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from superharness.utils.privacy import strip_private_tags

import logging
logger = logging.getLogger(__name__)


_ENV_NAME = "SUPERHARNESS_SUMMARIZER"
_ENV_RATE_LIMIT = "SUPERHARNESS_SUMMARIZER_MAX_PER_HOUR"


class SummarizerError(Exception):
    """Base class: unknown provider, missing credentials, transport faults."""


class RateLimitExceeded(SummarizerError):
    """Raised when a provider's per-hour budget is exhausted."""


@runtime_checkable
class Summarizer(Protocol):
    """Protocol every summarizer must implement."""

    def summarize(self, context: dict[str, Any]) -> str:
        ...


class NoopSummarizer:
    """Deterministic, network-free summarizer used as the default.

    Builds a short summary from the keys of the context dict. Strips
    `<private>...</private>` spans from any text it embeds.
    """

    def summarize(self, context: dict[str, Any]) -> str:
        task_id = context.get("task_id") or "unknown"
        phase = context.get("phase") or "unknown"
        title = context.get("title") or ""
        outcome = context.get("outcome") or ""
        from_agent = context.get("from_agent") or ""

        parts: list[str] = []
        parts.append(f"[{phase}] {task_id}")
        if title:
            parts.append(f"title: {title}")
        if from_agent:
            parts.append(f"by: {from_agent}")
        if outcome:
            parts.append(f"outcome: {outcome}")

        return strip_private_tags(" | ".join(parts))


@dataclass(frozen=True)
class SummarizerConfig:
    """Registry entry for a summarizer provider.

    max_per_hour=None disables rate limiting for that provider.
    default_model is passed to the provider class as `model=` if set;
    providers that take no model argument should ignore it.
    """
    provider_class: type
    max_per_hour: int | None = None
    default_model: str | None = None
    init_kwargs: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, SummarizerConfig] = {
    "noop": SummarizerConfig(provider_class=NoopSummarizer, max_per_hour=None),
}


def register_summarizer(name: str, config: SummarizerConfig) -> None:
    """Add a provider to the registry. Last write wins for a given name."""
    _REGISTRY[name.lower()] = config


def list_summarizers() -> list[str]:
    """Return registered provider names, sorted."""
    return sorted(_REGISTRY)


class _RateLimitedSummarizer:
    """Wrap a summarizer with a per-process token bucket.

    Bucket holds timestamps of the last N calls within a 1-hour window.
    Exceeding the budget raises RateLimitExceeded. Rate limit is
    per-process; spawn a new process and you get a fresh bucket.
    """

    def __init__(self, inner: Summarizer, max_per_hour: int) -> None:
        self._inner = inner
        self._max = max_per_hour
        self._calls: deque[float] = deque()
        self.provider_name: str = type(inner).__name__

    def summarize(self, context: dict[str, Any]) -> str:
        now = time.time()
        cutoff = now - 3600
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()
        if len(self._calls) >= self._max:
            raise RateLimitExceeded(
                f"summarizer rate limit reached: {self._max}/hour"
            )
        self._calls.append(now)
        return self._inner.summarize(context)


class _SQLiteRateLimitedSummarizer:
    """Wrap a summarizer with a SQLite-backed cross-process rate limit.

    Reads count via summarizer_calls DAO from the project's state DB.
    Multiple `shux` processes against the same project share one
    budget. Defensive: any DAO error falls back to allowing the call,
    so a broken state DB cannot block lifecycle transitions.

    Logs every call (success/failure) to summarizer_calls. The success
    flag means the inner summarizer returned without raising;
    transport-level errors are recorded as success=0 so that the rate
    limit budget is not eaten by transient failures (count_in_window
    defaults to successes only).
    """

    def __init__(
        self,
        inner: Summarizer,
        max_per_hour: int,
        project_dir: str,
        provider_name: str,
    ) -> None:
        self._inner = inner
        self._max = max_per_hour
        self._project_dir = project_dir
        self.provider_name = provider_name

    def _check_budget(self) -> None:
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import summarizer_calls
            conn = get_connection(self._project_dir)
            try:
                init_db(conn)
                used = summarizer_calls.count_in_window(
                    conn, self.provider_name, window_seconds=3600
                )
            finally:
                conn.close()
            if used >= self._max:
                raise RateLimitExceeded(
                    f"summarizer rate limit reached: {self._max}/hour "
                    f"({used} used in last 60m)"
                )
        except RateLimitExceeded:
            raise
        except Exception as e:
            logger.warning("summarizer.py unexpected error: %s", e, exc_info=True)
            return

    def _log(
        self,
        success: bool,
        *,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        try:
            from superharness.engine.db import get_connection, init_db
            from superharness.engine import summarizer_calls
            conn = get_connection(self._project_dir)
            try:
                init_db(conn)
                summarizer_calls.record_call(
                    conn,
                    provider=self.provider_name,
                    success=success,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            finally:
                conn.close()
        except Exception as e:
            logger.warning("summarizer.py unexpected error: %s", e, exc_info=True)
            return

    def summarize(self, context: dict[str, Any]) -> str:
        self._check_budget()
        try:
            text = self._inner.summarize(context)
        except Exception as e:
            logger.warning("summarizer.py unexpected error: %s", e, exc_info=True)
            self._log(success=False)
            raise
        usage = getattr(self._inner, "last_usage", None) or {}
        self._log(
            success=True,
            model=usage.get("model"),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        return text


def _resolve_max_per_hour(config: SummarizerConfig) -> int | None:
    """Apply env override on top of the config default."""
    raw = os.environ.get(_ENV_RATE_LIMIT)
    if raw:
        try:
            v = int(raw)
            return v if v > 0 else None
        except ValueError:
            pass
    return config.max_per_hour


def get_summarizer(
    name: str | None = None,
    *,
    project_dir: str | None = None,
) -> Summarizer:
    """Resolve a Summarizer instance.

    Selection order: explicit name, SUPERHARNESS_SUMMARIZER env, "noop".
    Unknown names raise SummarizerError. Providers that fail to
    construct (missing credentials, missing binary) raise
    SummarizerError.

    Rate-limited providers are returned wrapped. When `project_dir` is
    set, the wrapper is SQLite-backed (cross-process budget); when
    `project_dir` is None, the wrapper falls back to an in-memory
    bucket (per-process budget).
    """
    chosen = (name or os.environ.get(_ENV_NAME) or "noop").lower()
    config = _REGISTRY.get(chosen)
    if config is None:
        raise SummarizerError(
            f"unknown summarizer {chosen!r}. Known: {list_summarizers()}"
        )

    kwargs = dict(config.init_kwargs)
    if config.default_model and "model" not in kwargs:
        kwargs["model"] = config.default_model

    try:
        inner = config.provider_class(**kwargs)
    except SummarizerError:
        raise
    except Exception as e:
        raise SummarizerError(
            f"failed to construct {chosen} summarizer: {e}"
        ) from e

    max_per_hour = _resolve_max_per_hour(config)
    if max_per_hour is not None and max_per_hour > 0:
        if project_dir:
            return _SQLiteRateLimitedSummarizer(
                inner, max_per_hour, project_dir, provider_name=chosen
            )
        return _RateLimitedSummarizer(inner, max_per_hour)
    return inner


# Side-effect: trigger external provider registration at import time.
# The import is deliberately at the bottom: summarizer_providers depends
# on `register_summarizer`, `SummarizerConfig`, `SummarizerError`, etc.
try:  # pragma: no cover - exercised by integration tests
    from superharness.engine import summarizer_providers as _providers  # noqa: F401
except ImportError:
    pass
