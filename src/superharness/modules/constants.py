"""Module system constants — shared across loader, runner, and validator."""
from __future__ import annotations

# Stable lifecycle events that modules can hook into (SDK v1 contract)
LIFECYCLE_EVENTS: list[str] = [
    "on_close",
    "on_verify",
    "on_continue",
    "on_delegate",
    "on_watcher_tick",
]
