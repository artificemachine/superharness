"""Module runner — executes lifecycle hooks for enabled modules."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from .loader import load_modules

logger = logging.getLogger(__name__)

# Lifecycle events that modules can hook into
LIFECYCLE_EVENTS = [
    "on_close",
    "on_verify",
    "on_continue",
    "on_delegate",
    "on_watcher_tick",
]

# Action registry — maps action names to callables
# Each callable signature: (context: dict, settings: dict) -> dict
_ACTION_REGISTRY: dict[str, Callable[[dict, dict], dict]] = {}


def register_action(name: str, func: Callable[[dict, dict], dict]) -> None:
    """Register a module action function.

    Args:
        name: Action name referenced in module YAML
        func: Callable with signature (context, settings) -> result_dict
    """
    _ACTION_REGISTRY[name] = func


def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a minimal hook condition against the context.

    Supported grammar (only): ``<context_key> == '<value>'`` and
    ``<context_key> != '<value>'``. A condition restricts when a hook fires
    (e.g. openclaw routing only on ``target == 'openclaw'``), so anything we
    cannot parse fails closed (returns False) and is logged — never fire a
    restricted hook on a malformed condition.
    """
    for op in ("==", "!="):
        if op in condition:
            key, _, raw = condition.partition(op)
            want = raw.strip().strip("'\"")
            actual = str(context.get(key.strip()))
            equal = actual == want
            return equal if op == "==" else not equal
    logger.warning(f"Unparseable hook condition: {condition!r} — skipping hook")
    return False


def run_hooks(
    event: str,
    context: dict[str, Any],
    project_dir: Path,
) -> list[dict[str, Any]]:
    """Load modules and fire all hooks for the given lifecycle event.

    Args:
        event: Lifecycle event name (e.g., "on_close", "on_verify")
        context: Context dict passed to hook actions (task_id, summary, etc.)
        project_dir: Project root directory

    Returns:
        List of result dicts, one per fired hook
    """
    if event not in LIFECYCLE_EVENTS:
        logger.warning(f"Unknown lifecycle event: {event}")
        return []

    # Load all enabled modules
    modules = load_modules(project_dir)

    results = []

    for module in modules:
        # Check if module has a hook for this event
        if event not in module.hooks:
            continue

        hook_config = module.hooks[event]
        action_name = hook_config.get("action")

        if not action_name:
            logger.warning(f"Module {module.name} hook {event} missing 'action' field")
            continue

        # Conditional hook — skip silently when the condition is not met.
        condition = hook_config.get("condition")
        if condition and not _evaluate_condition(condition, context):
            logger.debug(
                f"{module.name}.{event} skipped — condition not met: {condition}"
            )
            continue

        # Look up action in registry
        action_func = _ACTION_REGISTRY.get(action_name)
        if not action_func:
            logger.warning(
                f"Module {module.name} references unknown action '{action_name}' "
                f"(available: {list(_ACTION_REGISTRY.keys())})"
            )
            results.append({
                "module": module.name,
                "event": event,
                "success": False,
                "error": f"Unknown action: {action_name}",
            })
            continue

        # Execute the action
        block_on = hook_config.get("block_on")
        try:
            logger.debug(f"Running {module.name}.{event} → {action_name}")
            result = action_func(context, module.settings)

            # A result gates the lifecycle step only when the hook explicitly
            # declares `block_on` AND the action reports a block. Without a
            # declared gate, an action's `blocked` flag is advisory and must
            # not stop the caller (e.g. verification).
            is_blocking = bool(block_on) and bool(result.get("blocked"))
            entry = {
                "module": module.name,
                "event": event,
                "success": True,
                **result,
                "blocked": is_blocking,
            }
            if block_on:
                entry["block_on"] = block_on
            results.append(entry)

        except Exception as e:
            logger.warning(
                f"Module {module.name} action {action_name} failed: {e}",
                exc_info=True,
            )
            results.append({
                "module": module.name,
                "event": event,
                "success": False,
                "error": str(e),
            })

    return results
