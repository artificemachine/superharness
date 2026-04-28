"""Event hook system — extensible lifecycle notifications.

Cherry-picked from hermes-agent/gateway/hooks.py.
"""
import os
import yaml
from dataclasses import dataclass, field


@dataclass
class HookDef:
    name: str
    events: list[str]
    handler_path: str
    enabled: bool = True


class HookRegistry:
    """Central registry for event hooks."""

    def __init__(self):
        self._hooks: dict[str, list[HookDef]] = {}

    def register(self, event: str, hook: HookDef) -> None:
        self._hooks.setdefault(event, []).append(hook)

    def fire(self, event: str, data: dict | None = None) -> None:
        """Fire all hooks registered for an event. Errors don't block."""
        for hook in self._hooks.get(event, []):
            if not hook.enabled:
                continue
            try:
                self._execute_handler(hook.handler_path, data or {})
            except Exception:
                pass

    def _execute_handler(self, path: str, data: dict) -> None:
        """Execute a handler script with event data as JSON env var."""
        import json
        import subprocess
        subprocess.run(
            [os.path.expanduser(path)],
            env={**os.environ, "HOOK_EVENT_DATA": json.dumps(data)},
            capture_output=True, timeout=30, check=False,
        )


_registry: HookRegistry | None = None


def get_registry() -> HookRegistry:
    global _registry
    if _registry is None:
        _registry = HookRegistry()
    return _registry


def load_hooks_from_dir(project_dir: str) -> int:
    """Load hooks from .superharness/hooks/. Returns count loaded."""
    hooks_dir = os.path.join(project_dir, ".superharness", "hooks")
    if not os.path.isdir(hooks_dir):
        return 0
    registry = get_registry()
    count = 0
    for entry in os.listdir(hooks_dir):
        yml_path = os.path.join(hooks_dir, entry, "HOOK.yaml")
        if not os.path.isfile(yml_path):
            continue
        try:
            with open(yml_path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            handler = config.get("handler", "handler.py")
            handler_path = os.path.join(hooks_dir, entry, handler)
            if not os.path.isfile(handler_path):
                continue
            hook = HookDef(
                name=config.get("name", entry),
                events=config.get("events", []),
                handler_path=handler_path,
            )
            for event in hook.events:
                registry.register(event, hook)
            count += 1
        except Exception:
            pass
    return count
