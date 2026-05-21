"""MCP HookRegistry — Iteration 2.

Lifecycle event system for task state changes.
Handlers are scoped per-project to prevent cross-contamination.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from typing import Callable, Any

logger = logging.getLogger(__name__)


class HookRegistry:
    """Thread-safe registry of per-project event handlers."""

    def __init__(self) -> None:
        # key: (event, project_path) → list of handlers
        self._handlers: dict[tuple[str, str], list[Callable]] = defaultdict(list)
        self._lock = threading.Lock()

    def register(self, event: str, handler: Callable, *, project_path: str) -> None:
        key = (event, project_path)
        with self._lock:
            self._handlers[key].append(handler)

    def unregister(self, event: str, handler: Callable, *, project_path: str) -> None:
        key = (event, project_path)
        with self._lock:
            lst = self._handlers.get(key, [])
            try:
                lst.remove(handler)
            except ValueError:
                pass

    def fire(self, event: str, payload: Any, *, project_path: str) -> None:
        key = (event, project_path)
        with self._lock:
            handlers = list(self._handlers.get(key, []))
        for handler in handlers:
            try:
                handler(payload)
            except Exception as e:
                logger.warning("hooks.py unexpected error: %s", e, exc_info=True)
                logger.exception("Hook handler raised for event '%s' on project '%s'", event, project_path)

    def load_hooks_dir(self, project_path: str) -> None:
        """Auto-import .superharness/hooks/*.py and register any exported hooks."""
        import os
        import importlib.util
        hooks_dir = os.path.join(project_path, ".superharness", "hooks")
        if not os.path.isdir(hooks_dir):
            return
        for fname in os.listdir(hooks_dir):
            if not fname.endswith(".py"):
                continue
            event = fname[3:].replace(".py", "").replace("_", ":") if fname.startswith("on_") else None
            if not event:
                continue
            try:
                spec = importlib.util.spec_from_file_location(fname, os.path.join(hooks_dir, fname))
                mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                if hasattr(mod, "handler"):
                    self.register(event, mod.handler, project_path=project_path)
            except Exception as e:
                logger.warning("hooks.py unexpected error: %s", e, exc_info=True)
                logger.exception("Failed to load hook file: %s", fname)


# Module-level singleton
_registry = HookRegistry()


def get_registry() -> HookRegistry:
    return _registry
