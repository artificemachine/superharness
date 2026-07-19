"""Harness registry: name -> Harness adapter.

See docs/PLAN-steal-omnigent.md iterations 5-6.

Resolved ambiguity (see the executor's final report for iteration 5):
the plan assumed inbox_dispatch.py builds per-agent CLI argv directly and
that this registry would be wired in there. In the real repo,
inbox_dispatch.py never builds agent-specific argv — it always shells out
generically to `python -m superharness.commands.delegate --to <agent> ...`.
The actual per-agent invocation assembly (agent binary via a bash launcher
script resolved from adapter_registry manifests) lives in delegate.py's
`_launch_agent()`, which is where this registry is actually consulted.
"""
from __future__ import annotations

from superharness.harnesses.base import Harness, Invocation

_REGISTRY: dict[str, Harness] = {}


def register(name: str, harness: Harness) -> None:
    _REGISTRY[name] = harness


def get_harness(name: str) -> Harness:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"Unknown harness {name!r}. Known harnesses: {sorted(_REGISTRY)}"
        ) from None


def _register_builtins() -> None:
    from superharness.harnesses.claude import ClaudeHarness
    from superharness.harnesses.codex import CodexHarness
    from superharness.harnesses.gemini import GeminiHarness
    from superharness.harnesses.opencode import OpencodeHarness

    register("claude-code", ClaudeHarness())
    register("codex-cli", CodexHarness())
    register("gemini-cli", GeminiHarness())
    register("opencode", OpencodeHarness())


_register_builtins()

# Snapshot of registered names, safe to import for iteration purposes.
# Builtins register eagerly at import time (above), so this always reflects
# every adapter registered by this module.
KNOWN_HARNESSES: list[str] = sorted(_REGISTRY)

__all__ = ["Harness", "Invocation", "get_harness", "register", "KNOWN_HARNESSES"]
