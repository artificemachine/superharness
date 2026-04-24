"""Failure pattern matching — classify agent errors and surface fix hints.

When a task fails, match the error output against a known pattern library.
Matched patterns are stored in failures.yaml and injected into the next
dispatch's context so the agent avoids repeating the same mistake.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


@dataclass
class FailurePattern:
    """One recognizable failure signature with a fix hint."""
    id: str
    description: str
    # Any of these regexes matching in the error text triggers this pattern
    match_patterns: list[str]
    # Hint injected into the next dispatch prompt
    hint: str
    # Optional: what to check/fix before retrying
    remediation: str = ""
    severity: str = "minor"  # minor | major | critical


# ---------------------------------------------------------------------------
# Built-in pattern library
# ---------------------------------------------------------------------------

BUILTIN_PATTERNS: list[FailurePattern] = [
    FailurePattern(
        id="import_error",
        description="Python ImportError or ModuleNotFoundError",
        match_patterns=[
            r"ImportError",
            r"ModuleNotFoundError",
            r"cannot import name",
            r"No module named",
        ],
        hint="A Python import failed. Check that all dependencies are installed (`pip install -e .`) and that import paths use the correct package names.",
        remediation="Run `pip install -e .` in the project root before retrying.",
        severity="major",
    ),
    FailurePattern(
        id="permission_denied",
        description="File permission denied",
        match_patterns=[
            r"PermissionError",
            r"Permission denied",
            r"\[Errno 13\]",
        ],
        hint="A file permission error occurred. Ensure the target files are writable and not locked by another process.",
        severity="major",
    ),
    FailurePattern(
        id="file_not_found",
        description="File or directory not found",
        match_patterns=[
            r"FileNotFoundError",
            r"No such file or directory",
            r"\[Errno 2\]",
        ],
        hint="A required file or directory was not found. Verify paths are correct and that prerequisite setup steps have run.",
        severity="major",
    ),
    FailurePattern(
        id="git_conflict",
        description="Git merge conflict",
        match_patterns=[
            r"CONFLICT",
            r"Automatic merge failed",
            r"<<<<<<< HEAD",
            r"merge conflict",
        ],
        hint="A git merge conflict exists. Resolve conflicts in the affected files before retrying the task.",
        remediation="Run `git status` to see conflicting files, resolve them, then `git add` and continue.",
        severity="critical",
    ),
    FailurePattern(
        id="git_dirty",
        description="Git working tree has uncommitted changes",
        match_patterns=[
            r"Your local changes to the following files would be overwritten",
            r"Please commit your changes or stash them",
            r"error: cannot checkout",
        ],
        hint="The git working tree has uncommitted changes that block the operation. Commit or stash changes before retrying.",
        severity="major",
    ),
    FailurePattern(
        id="test_failure",
        description="Unit/integration test assertion failed",
        match_patterns=[
            r"AssertionError",
            r"FAILED tests/",
            r"pytest.*error",
            r"assert .* ==",
            r"Expected.*Got",
        ],
        hint="One or more tests failed. Review the test output, fix the failing assertions, and run tests locally before marking the task done.",
        severity="major",
    ),
    FailurePattern(
        id="syntax_error",
        description="Python syntax error",
        match_patterns=[
            r"SyntaxError",
            r"IndentationError",
            r"invalid syntax",
        ],
        hint="A Python syntax error was introduced. Run `python -m py_compile <file>` to find and fix the syntax issue before retrying.",
        severity="major",
    ),
    FailurePattern(
        id="type_error",
        description="Python TypeError",
        match_patterns=[
            r"TypeError",
            r"takes \d+ positional argument",
            r"unexpected keyword argument",
            r"object is not callable",
        ],
        hint="A TypeError occurred, typically from wrong argument types or counts. Check function signatures and call sites.",
        severity="minor",
    ),
    FailurePattern(
        id="timeout",
        description="Operation timed out",
        match_patterns=[
            r"TimeoutError",
            r"timed out",
            r"deadline exceeded",
            r"SIGALRM",
            r"budget.*exceeded",
            r"cost.*exceeded",
        ],
        hint="The operation timed out or exceeded budget. Consider breaking the task into smaller pieces or increasing the budget limit.",
        remediation="Split the task into subtasks or increase max_budget_usd / max_turns.",
        severity="major",
    ),
    FailurePattern(
        id="api_auth",
        description="API authentication or rate-limit error",
        match_patterns=[
            r"AuthenticationError",
            r"401 Unauthorized",
            r"403 Forbidden",
            r"invalid.*api.?key",
            r"rate.?limit",
            r"overloaded",
        ],
        hint="An API authentication or rate-limit error occurred. Check that the API key is valid and not exhausted. Wait before retrying if rate-limited.",
        severity="critical",
    ),
    FailurePattern(
        id="disk_space",
        description="Disk space exhausted",
        match_patterns=[
            r"No space left on device",
            r"\[Errno 28\]",
            r"disk.*full",
        ],
        hint="The disk is full. Free up space before retrying.",
        severity="critical",
    ),
    FailurePattern(
        id="lock_contention",
        description="Lock or mutex contention",
        match_patterns=[
            r"already running",
            r"lock.*held",
            r"another process",
            r"\.lock\b",
            r"MkdirLock",
        ],
        hint="A lock was held by another process. Check for orphaned lock files or wait for the other process to finish.",
        remediation="Run `shux doctor` to check for stale locks and clean them up.",
        severity="minor",
    ),
    FailurePattern(
        id="yaml_parse",
        description="YAML parsing error",
        match_patterns=[
            r"yaml.scanner.ScannerError",
            r"yaml.parser.ParserError",
            r"mapping values are not allowed",
            r"could not find expected",
        ],
        hint="A YAML file has a parse error. Check indentation and quoting in the affected file.",
        severity="major",
    ),
    FailurePattern(
        id="worktree_error",
        description="Git worktree creation or management error",
        match_patterns=[
            r"worktree",
            r"already checked out",
            r"is already a working tree",
        ],
        hint="A git worktree error occurred. Run `git worktree list` to see current worktrees and `git worktree prune` to clean stale ones.",
        remediation="Run `git worktree prune` then retry.",
        severity="major",
    ),
]

# Build a fast lookup by id
PATTERN_BY_ID: dict[str, FailurePattern] = {p.id: p for p in BUILTIN_PATTERNS}


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

def match_patterns(error_text: str) -> list[FailurePattern]:
    """Return all patterns that match the given error text (case-insensitive)."""
    matched = []
    for pattern in BUILTIN_PATTERNS:
        for regex in pattern.match_patterns:
            if re.search(regex, error_text, re.IGNORECASE):
                matched.append(pattern)
                break
    return matched


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences and terminal noise (BEL, BS) from text."""
    # Standard ANSI escape sequences (CSI, OSC, etc)
    ansi_escape = re.compile(r'(?:\x1B[@-Z\\-_]|[\x80-\x9F]|\x1B\[[0-?]*[ -/]*[@-~])')
    text = ansi_escape.sub('', text)
    # Also strip BEL, BS, and other common terminal noise
    text = re.sub(r'[\x07\x08]', '', text)
    return text


# ---------------------------------------------------------------------------
# Storage — failures.yaml integration
# ---------------------------------------------------------------------------

def _load_failures(failures_file: str) -> dict:
    if yaml is None:
        return {"failures": []}
    p = Path(failures_file)
    if not p.exists():
        return {"failures": []}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            data = {}
        if "failures" not in data or not isinstance(data["failures"], list):
            data["failures"] = []
        return data
    except Exception:
        return {"failures": []}


def _save_failures(failures_file: str, data: dict) -> None:
    if yaml is None:
        return
    Path(failures_file).write_text(
        yaml.safe_dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def record_failure(
    project_dir: str,
    task_id: str,
    error_text: str,
    agent: str = "claude-code",
    extra: dict | None = None,
) -> list[FailurePattern]:
    """Analyze error_text, match against pattern library, and append to failures.yaml.

    Returns the list of matched patterns (empty if no match).
    """
    failures_file = str(Path(project_dir) / ".superharness" / "failures.yaml")
    data = _load_failures(failures_file)

    matched = match_patterns(error_text)
    pattern_ids = [p.id for p in matched]

    _sev_rank = {"minor": 0, "major": 1, "critical": 2}
    entry: dict[str, Any] = {
        "task": task_id,
        "agent": agent,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "patterns": pattern_ids if pattern_ids else ["unknown"],
        "error_snippet": strip_ansi(error_text[:500]).strip(),
        "severity": max((p.severity for p in matched), default="minor",
                        key=lambda s: _sev_rank.get(s, 0)),
    }
    # Only allow safe extra keys — never overwrite core fields
    _safe_extra_keys = {"context", "retry_count", "slot_index", "model"}
    if extra:
        for k, v in extra.items():
            if k in _safe_extra_keys:
                entry[k] = v

    data["failures"].append(entry)
    try:
        _save_failures(failures_file, data)
    except Exception:
        pass

    return matched


def get_failure_hints(project_dir: str, task_id: str) -> list[str]:
    """Return fix hints for all recorded failures for a given task_id.

    Called by _build_context_hint in delegate.py to inject remediation advice
    into the next dispatch prompt.
    """
    failures_file = str(Path(project_dir) / ".superharness" / "failures.yaml")
    data = _load_failures(failures_file)

    # Collect pattern_ids from all failures matching this task
    seen_pattern_ids: set[str] = set()
    for entry in data.get("failures", []):
        if entry.get("task") == task_id:
            for pid in entry.get("patterns", []):
                seen_pattern_ids.add(pid)

    hints = []
    if "unknown" in seen_pattern_ids and not seen_pattern_ids.difference({"unknown"}):
        hints.append("[unknown] An unclassified error occurred. Check the error_snippet in failures.yaml for details.")

    for pid in seen_pattern_ids:
        if pid == "unknown":
            continue
        pattern = PATTERN_BY_ID.get(pid)
        if pattern:
            hint_line = f"[{pattern.id}] {pattern.hint}"
            if pattern.remediation:
                hint_line += f" Remediation: {pattern.remediation}"
            hints.append(hint_line)

    return hints
