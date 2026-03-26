"""Superharness module system — opt-in enhancements."""
from __future__ import annotations

from .runner import register_action


def register_all_actions() -> None:
    """Register all built-in module actions."""
    # Import and register Obsidian actions
    try:
        from .actions.obsidian import obsidian_write_note
        register_action("obsidian_write_note", obsidian_write_note)
    except ImportError:
        pass  # Module not available yet

    # Import and register auto-schedule actions
    try:
        from .actions.auto_schedule import check_scheduled_tasks
        register_action("check_scheduled_tasks", check_scheduled_tasks)
    except ImportError:
        pass  # Module not available yet

    # Import and register security actions
    try:
        from .actions.security import security_scan
        register_action("security_scan", security_scan)
    except ImportError:
        pass  # Module not available yet

    # Import and register remember actions
    try:
        from .actions.remember import refresh_context
        register_action("refresh_context", refresh_context)
    except ImportError:
        pass  # Module not available yet

    # Import and register ntfy actions
    try:
        from .actions.ntfy import ntfy_send
        register_action("ntfy_send", ntfy_send)
    except ImportError:
        pass  # Module not available yet

    # Import and register ship actions
    try:
        from .actions.ship import git_ship
        register_action("git_ship", git_ship)
    except ImportError:
        pass  # Module not available yet


# Auto-register actions on module import
register_all_actions()
