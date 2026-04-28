"""Thread-safe approval state with risk classification and persistence."""
from __future__ import annotations

import json
import os
import re
import threading


# Low-risk patterns: read-only or non-destructive commands
_LOW_RISK_PATTERNS = [
    r"^echo\s", r"^ls\s", r"^pwd$", r"^cat\s", r"^head\s",
    r"^tail\s", r"^grep\s", r"^wc\s", r"^sort\s", r"^uniq\s",
    r"^find\s.*-name", r"^which\s", r"^type\s", r"^env$",
    r"^printenv", r"^date", r"^whoami", r"^id$",
]
# High-risk patterns: destructive or dangerous
_HIGH_RISK_PATTERNS = [
    r"rm\s+-rf", r"dd\s+if=", r">\s*/dev/sd", r"mkfs\.",
    r"chmod\s+777", r"chown\s+-R", r"kill\s+-9",
    r"reboot", r"shutdown", r":\(\)\s*\{",
]


class ApprovalState:
    def __init__(self, config_path: str | None = None):
        self._once: set[str] = set()
        self._session: set[str] = set()
        self._permanent: set[str] = set()
        self._lock = threading.Lock()
        self._config_path = config_path
        if config_path and os.path.isfile(config_path):
            self._load()

    def approve(self, command: str, scope: str = "once") -> None:
        with self._lock:
            if scope == "permanent":
                self._permanent.add(command.split()[0] if command.strip() else command)
                self._save()
            elif scope == "session":
                self._session.add(command.split()[0] if command.strip() else command)
            else:
                self._once.add(command)

    def is_approved(self, command: str) -> bool:
        with self._lock:
            if command in self._once:
                return True
            prefix = command.split()[0] if command.strip() else command
            return prefix in self._session or prefix in self._permanent

    def reset(self) -> None:
        with self._lock:
            self._once.clear()
            self._session.clear()

    def check_risk(self, command: str) -> str:
        """Classify command risk: low, medium, or high."""
        if not command or not command.strip():
            return "low"
        for pattern in _HIGH_RISK_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return "high"
        for pattern in _LOW_RISK_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return "low"
        return "medium"

    def _save(self) -> None:
        if not self._config_path:
            return
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w") as f:
                json.dump({"permanent": sorted(self._permanent)}, f)
        except Exception:
            pass

    def _load(self) -> None:
        try:
            with open(self._config_path) as f:
                data = json.load(f)
            self._permanent = set(data.get("permanent", []))
        except Exception:
            pass
