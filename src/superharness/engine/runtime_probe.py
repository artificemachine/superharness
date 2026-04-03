"""Python runtime probe — prevents interpreter mismatch bugs.

Superharness relies on several third-party modules (yaml, pydantic, click, …).
When the OS launches the watcher from launchd, systemd, or Windows Task
Scheduler it may pick a different ``python`` than the one the user pip-installed
superharness into.  This module detects that mismatch early and surfaces a
clear error.

Public API
----------
probe_runtime(override=None) -> str
    Return the path to the Python interpreter that should be used for all
    superharness subprocesses.  Respects ``SUPERHARNESS_PYTHON`` env var and
    the ``python_executable`` field in ``watcher.yaml`` (if present).

probe_required_modules(modules) -> None
    Verify that *modules* are importable in the current interpreter.
    Raises ``ImportError`` on the first missing module.

persist_runtime(watcher_yaml_path, interpreter) -> None
    Write ``python_executable: <interpreter>`` into ``watcher.yaml`` so that
    the service installer can use it when registering the scheduled task.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Interpreter discovery
# ---------------------------------------------------------------------------


def probe_runtime(override: str | None = None) -> str:
    """Return the Python interpreter path to use for watcher subprocesses.

    Resolution order:
    1. *override* argument (highest priority — used by tests and CLI flags)
    2. ``SUPERHARNESS_PYTHON`` environment variable
    3. ``sys.executable`` (the interpreter currently running this code)

    Args:
        override: Explicit interpreter path.  Pass ``None`` to use env / default.

    Returns:
        Absolute path (or command name) of the chosen interpreter.
    """
    if override:
        return override
    env_val = os.environ.get("SUPERHARNESS_PYTHON", "").strip()
    if env_val:
        return env_val
    return sys.executable


# ---------------------------------------------------------------------------
# Module availability check
# ---------------------------------------------------------------------------


def probe_required_modules(modules: list[str]) -> None:
    """Verify that each module in *modules* can be imported.

    Uses ``importlib.import_module`` in the *current* interpreter.  For a
    check against an *external* interpreter, use :func:`probe_runtime_modules`.

    Args:
        modules: List of dotted module names, e.g. ``['yaml', 'pydantic']``.

    Raises:
        ImportError: On the first module that cannot be imported.
    """
    import importlib

    for mod in modules:
        try:
            importlib.import_module(mod)
        except ImportError as exc:
            raise ImportError(
                f"superharness: required module '{mod}' is not importable in "
                f"{sys.executable!r}.  "
                f"Install it with: {sys.executable} -m pip install {mod.split('.')[0]}"
            ) from exc


# ---------------------------------------------------------------------------
# Cross-interpreter module probe
# ---------------------------------------------------------------------------

#: Minimum set of modules required by the superharness watcher.
REQUIRED_MODULES: list[str] = [
    "yaml",
    "click",
    "pydantic",
    "superharness.engine.inbox",
]


def probe_runtime_modules(interpreter: str, modules: list[str] | None = None) -> list[str]:
    """Check which *modules* are importable under *interpreter*.

    Runs a subprocess using *interpreter* to attempt each import.

    Args:
        interpreter: Path to the Python interpreter to test.
        modules:     List of module names.  Defaults to :data:`REQUIRED_MODULES`.

    Returns:
        List of module names that *failed* to import (empty = all good).
    """
    if modules is None:
        modules = REQUIRED_MODULES

    failed: list[str] = []
    for mod in modules:
        try:
            result = subprocess.run(
                [interpreter, "-c", f"import {mod}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                failed.append(mod)
        except (OSError, subprocess.TimeoutExpired):
            failed.append(mod)
    return failed


# ---------------------------------------------------------------------------
# Persist runtime in watcher.yaml
# ---------------------------------------------------------------------------


def persist_runtime(watcher_yaml_path: str | Path, interpreter: str) -> None:
    """Upsert ``python_executable`` in ``watcher.yaml``.

    If ``watcher.yaml`` does not exist it is created.  Existing keys are
    preserved.  Uses a simple line-by-line approach to avoid reformatting the
    entire file.

    Args:
        watcher_yaml_path: Path to ``.superharness/watcher.yaml``.
        interpreter:       Interpreter path to persist.
    """
    path = Path(watcher_yaml_path)

    # Read existing content (or start fresh)
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        lines = []

    key = "python_executable"
    new_line = f'{key}: "{interpreter}"\n'
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}:"):
            lines[i] = new_line
            updated = True
            break

    if not updated:
        lines.append(new_line)

    path.write_text("".join(lines), encoding="utf-8")
