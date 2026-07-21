"""Domain-error hierarchy for CLI-facing failures (PLAN-coding-practices.md
iteration 6).

Historically, engine/ modules called the sys module's exit builtin directly,
sometimes deep inside library functions (e.g. engine/contract.py's
latest_handoff_task, not just its CLI-only main()). That makes those
functions impossible to call in-process without risking an unintended
process exit, and impossible to test without asserting on SystemExit
specifically rather than a normal exception type.

This module gives engine code a way to say "this CLI invocation should end
with exit code N and this message on stderr" without actually exiting: raise
a SuperharnessError and let it propagate as an ordinary exception until it
reaches a CLI boundary. `handle_cli_error` is the one place that turns that
exception into stderr text and a real process exit — nothing outside this
module should ever terminate the process directly in response to catching
one.

A "CLI boundary" in this codebase is not a single physical call site: most
engine/ modules are invoked as standalone subprocesses via
`python -m superharness.engine.<module>` (see cli.py's `_run_module`), so
each module's own `if __name__ == "__main__":` guard is its boundary. The
one exception is engine/operator.py, whose Operator.start_stack() is called
in-process by cli.py's `operator start` command — cli.py catches it
directly. `handle_cli_error` is reused at every one of those boundaries, so
the exception -> exit-code translation logic itself has exactly one
implementation, even though it is invoked from more than one location.

Kept deliberately flat: SuperharnessError plus two subclasses is enough for
every site iterations 6 and 7 migrate. Do not add a third without a call
site that genuinely cannot be expressed as UsageError or OperationError.
"""
from __future__ import annotations

import sys


class SuperharnessError(Exception):
    """Base class for a domain error that should end a CLI invocation with
    a specific exit code. `message` may be empty — several migrated sites
    exited with a bare return code after already printing their
    diagnostics elsewhere, and `handle_cli_error` must not print anything
    extra in that case to keep CLI output byte-identical to the
    pre-refactor behaviour.
    """

    def __init__(self, message: str = "", *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class UsageError(SuperharnessError):
    """Bad, missing, or invalid CLI arguments."""


class OperationError(SuperharnessError):
    """A requested operation could not complete: bad state, a parse
    failure, a failed validation/hygiene check, and similar."""


def handle_cli_error(err: SuperharnessError) -> None:
    """The single place that turns a SuperharnessError into stderr text
    plus a process exit. Call this from a CLI boundary; nothing else in
    this codebase should terminate the process directly in response to
    catching a SuperharnessError.
    """
    text = str(err)
    if text:
        print(text, file=sys.stderr)
    sys.exit(err.exit_code)
