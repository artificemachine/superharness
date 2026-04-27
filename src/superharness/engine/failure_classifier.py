"""Failure classifier — turn a (launcher_rc, error_text, log_tail) into a category.

Replaces the silent `failed_reason: "launcher exited with code 1"` pattern with
an actionable classification that drives:
  - auto_retry decisions (skip permanent blocks and quota)
  - dashboard error surface (group by class, show explain)
  - failure_patterns recording (already exists, this layer is structural)

Categories:
  permanent_block - retrying produces same failure (bash crash, missing task,
                    syntax error). Surface to operator.
  transient       - timeout, network blip. Retry with backoff.
  quota           - rate limit, budget exhausted. Surface to operator.
  agent_crash     - agent process died (Python traceback, segfault). Retry once.
  no_op           - agent ran but produced no artifact. Surface (likely prompt bug).
  unknown         - anything we cannot classify. Default: retry once.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Category = Literal[
    "permanent_block",
    "transient",
    "quota",
    "agent_crash",
    "no_op",
    "unknown",
]


@dataclass(frozen=True)
class FailureClassification:
    category: Category
    retryable: bool
    explain: str  # human-readable, surfaces in dashboard and failed_reason


# Order matters: more specific patterns first.
_PATTERNS: list[tuple[str, Category, bool, str]] = [
    # permanent_block
    (
        r"unbound variable",
        "permanent_block",
        False,
        "bash unbound variable (likely empty array with set -u)",
    ),
    (
        r"command not found|No such file or directory",
        "permanent_block",
        False,
        "command or file not found",
    ),
    (
        r"task not found in contract|task does not exist",
        "permanent_block",
        False,
        "task not found in contract",
    ),
    (
        r"syntax error near unexpected token|line \d+: syntax error",
        "permanent_block",
        False,
        "shell syntax error",
    ),
    (
        r"permission denied",
        "permanent_block",
        False,
        "permission denied (chmod or owner issue)",
    ),
    # quota
    (
        r"rate limit|quota exceeded|budget exhausted|429 Too Many",
        "quota",
        False,
        "agent quota or rate limit exceeded",
    ),
    # agent_crash
    (
        r"Traceback \(most recent call last\)|Segmentation fault|panic:",
        "agent_crash",
        True,
        "agent crashed (Python traceback or panic)",
    ),
]


def classify(
    *, launcher_rc: int, error_text: str = "", log_tail: str = ""
) -> FailureClassification:
    """Classify a dispatch failure into a structured category.

    Args:
      launcher_rc: exit code of the launcher subprocess.
      error_text:  failed_reason string from upstream, often empty.
      log_tail:    last N lines of the launcher log file. May be empty.

    Returns:
      FailureClassification with .category, .retryable, .explain set.
    """
    haystack = "\n".join(s for s in (error_text or "", log_tail or "") if s)

    # Special case: rc=124 from coreutils timeout(1)
    if launcher_rc == 124:
        return FailureClassification(
            category="transient",
            retryable=True,
            explain="launcher timed out",
        )

    # Special case: lifecycle gate permanent block
    if launcher_rc == 2:
        return FailureClassification(
            category="permanent_block",
            retryable=False,
            explain="lifecycle gate rejected (permanent block)",
        )

    # Pattern scan
    for pat, cat, retryable, explain in _PATTERNS:
        if re.search(pat, haystack, re.IGNORECASE):
            return FailureClassification(
                category=cat, retryable=retryable, explain=explain
            )

    # rc=0 with nothing in logs means agent ran but did nothing useful
    if launcher_rc == 0 and not haystack.strip():
        return FailureClassification(
            category="no_op",
            retryable=False,
            explain="agent ran but produced no artifact",
        )

    # Fallback
    return FailureClassification(
        category="unknown",
        retryable=True,
        explain=f"unclassified failure (exit code {launcher_rc})",
    )
