"""Detector that scans commands against dangerous patterns."""
from superharness.guard.dangerous_patterns import DANGEROUS_PATTERNS


def detect_dangerous_command(command: str) -> tuple[bool, str]:
    """Check if a shell command matches any dangerous pattern.

    Returns (is_dangerous: bool, matched_pattern_label: str).
    If not dangerous, returns (False, "").
    """
    if not command or not command.strip():
        return (False, "")
    for pattern, label in DANGEROUS_PATTERNS:
        if pattern.search(command):
            return (True, label)
    return (False, "")
