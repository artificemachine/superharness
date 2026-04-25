from __future__ import annotations

class StateError(Exception):
    """Base for all state-backend errors."""

class ConnectionError(StateError):
    """Raised when the DB cannot be opened or PRAGMA setup fails."""

class SchemaError(StateError):
    """Raised on version mismatch, missing tables, or migration failure."""

class ConcurrencyError(StateError):
    """Raised on optimistic-concurrency version conflicts."""

class NotFoundError(StateError):
    """Raised when a required row is absent (use sparingly; prefer None returns)."""

class ParityError(StateError):
    """Raised when dual-write parity check finds unreconcilable drift."""

class SingletonConflict(StateError):
    """Raised when two watchers try to hold the singleton lease simultaneously."""
