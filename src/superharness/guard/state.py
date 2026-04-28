"""Thread-safe approval state for dangerous commands."""
from __future__ import annotations

import threading


class ApprovalState:
    """Per-session approval tracking with scoped persistence.

    Scopes:
      once    - approve exact command string only
      session - approve all commands matching same prefix
    """

    def __init__(self) -> None:
        self._once_approved: set[str] = set()
        self._session_approved: set[str] = set()
        self._lock = threading.Lock()

    def approve(self, command: str, scope: str = "once") -> None:
        with self._lock:
            if scope == "session":
                prefix = command.split()[0] if command.strip() else command
                self._session_approved.add(prefix)
            else:
                self._once_approved.add(command)

    def is_approved(self, command: str) -> bool:
        with self._lock:
            if command in self._once_approved:
                return True
            prefix = command.split()[0] if command.strip() else command
            return prefix in self._session_approved

    def reset(self) -> None:
        with self._lock:
            self._once_approved.clear()
            self._session_approved.clear()
