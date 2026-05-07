"""Model fallback chain for agent dispatch.

When a primary model times out or returns an error, the chain falls through
to progressively cheaper/faster alternatives.  The caller supplies a callable
that wraps one model invocation; the chain retries with each fallback model
until one succeeds or the chain is exhausted.

Usage::

    from superharness.engine.model_fallback import FallbackChain, FallbackExhausted

    def run_with_model(model: str) -> str:
        ...  # call agent with model, raise TimeoutError or RuntimeError on failure

    chain = FallbackChain(agent="claude-code")
    result = chain.run(run_with_model)
"""
from __future__ import annotations

import logging
import time
from typing import Callable, Any

from superharness.engine.model_router import MODEL_MAP, VALID_TIERS, _FALLBACK_TIER

logger = logging.getLogger(__name__)


class FallbackExhausted(Exception):
    """Raised when every model in the chain has been tried and all failed."""

    def __init__(self, agent: str, tried: list[str], last_error: Exception) -> None:
        self.agent = agent
        self.tried = tried
        self.last_error = last_error
        super().__init__(
            f"All models exhausted for agent '{agent}' ({tried}): {last_error}"
        )


_TIER_ORDER: list[str] = ["max", "standard", "mini"]


def _fallback_sequence(agent: str, starting_tier: str = "standard") -> list[str]:
    """Return model names from starting_tier down to mini, skipping unknowns."""
    agent_map = MODEL_MAP.get(agent, {})
    start_idx = _TIER_ORDER.index(starting_tier) if starting_tier in _TIER_ORDER else 1
    result: list[str] = []
    for tier in _TIER_ORDER[start_idx:]:
        model = agent_map.get(tier)
        if model:
            result.append(model)
    return result


class FallbackChain:
    """Execute a callable with a model name, falling back on timeout/error.

    Args:
        agent: Agent identifier (e.g. "claude-code").
        starting_tier: Initial tier to attempt ("max", "standard", "mini").
        retry_delay: Seconds to wait between attempts (default 0 for tests).
        timeout_exceptions: Exception types that trigger fallback (default TimeoutError).
        error_exceptions: Additional exception types that also trigger fallback.
    """

    def __init__(
        self,
        agent: str,
        starting_tier: str = _FALLBACK_TIER,
        retry_delay: float = 0.0,
        timeout_exceptions: tuple[type[Exception], ...] = (TimeoutError,),
        error_exceptions: tuple[type[Exception], ...] = (),
    ) -> None:
        self.agent = agent
        self.starting_tier = starting_tier
        self.retry_delay = retry_delay
        self._trigger = timeout_exceptions + error_exceptions
        self._chain = _fallback_sequence(agent, starting_tier)

    @property
    def chain(self) -> list[str]:
        return list(self._chain)

    def run(self, fn: Callable[[str], Any]) -> Any:
        """Call fn(model_name) for each model in chain until one succeeds.

        Args:
            fn: Callable that accepts a model name string and returns a result.
                Should raise TimeoutError (or configured exceptions) on failure.

        Returns:
            The return value of the first successful fn call.

        Raises:
            FallbackExhausted: If every model in the chain raises a trigger exception.
            Exception: Any non-trigger exception from fn is propagated immediately.
        """
        if not self._chain:
            raise FallbackExhausted(self.agent, [], RuntimeError("no models available"))

        tried: list[str] = []
        last_err: Exception = RuntimeError("unreachable")

        for model in self._chain:
            tried.append(model)
            try:
                result = fn(model)
                if len(tried) > 1:
                    logger.info(
                        "model_fallback: succeeded with %s after %d attempt(s)",
                        model, len(tried)
                    )
                return result
            except self._trigger as exc:
                last_err = exc
                logger.warning(
                    "model_fallback: %s failed with %s, trying next in chain",
                    model, type(exc).__name__
                )
                if self.retry_delay > 0:
                    time.sleep(self.retry_delay)

        raise FallbackExhausted(self.agent, tried, last_err)
