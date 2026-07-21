"""engine/errors.py — the domain-error hierarchy iteration 6 of
PLAN-coding-practices.md introduces, plus the CLI boundary that translates a
raised `SuperharnessError` back into the same stderr text and process exit
code the old scattered `sys.exit()` calls produced.

Background: most engine/ modules (contract.py, recall.py, validate.py,
profile.py, detect.py) are invoked as standalone subprocesses via
`python -m superharness.engine.<module>` (see cli.py's `_run_module`), so
each module's own `if __name__ == "__main__":` guard is its actual CLI
boundary — there is no single physical call site that can catch every
raise. `engine/operator.py` is the one exception: `Operator.start_stack()`
is imported and called in-process by `cli.py`'s `operator start` command,
so its raise is caught directly in cli.py. `handle_cli_error` is the one
piece of exception -> exit-code translation logic, reused from every one of
those boundaries — that is the "single handler" this iteration establishes,
even though the subprocess architecture means it is invoked from several
physical locations.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from superharness.engine.errors import (
    OperationError,
    SuperharnessError,
    UsageError,
    handle_cli_error,
)
from superharness.engine import contract

PYTHON = sys.executable
_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "err, expected_code, expect_stderr",
    [
        (SuperharnessError("boom", exit_code=1), 1, "boom"),
        (UsageError("bad args", exit_code=2), 2, "bad args"),
        (OperationError("op failed", exit_code=1), 1, "op failed"),
        (OperationError("", exit_code=1), 1, None),
        (SuperharnessError("", exit_code=0), 0, None),
    ],
)
def test_cli_maps_each_error_to_its_documented_exit_code(capsys, err, expected_code, expect_stderr):
    """handle_cli_error must reproduce exactly what the old sys.exit() call
    would have produced: the same exit code, and — only when the original
    site actually printed something — the same stderr text. An empty
    message must print nothing (several migrated sites relied on a bare
    `sys.exit(rc)` after already printing their diagnostics elsewhere)."""
    with pytest.raises(SystemExit) as exc_info:
        handle_cli_error(err)
    assert exc_info.value.code == expected_code
    captured = capsys.readouterr()
    if expect_stderr is None:
        assert captured.err == ""
    else:
        assert expect_stderr in captured.err
    assert captured.out == ""


def test_engine_error_is_catchable_without_systemexit():
    """A SuperharnessError is a plain Exception — raising and catching it
    must never involve SystemExit, so engine functions that raise one stay
    callable and testable in-process without a test needing
    pytest.raises(SystemExit)."""
    with pytest.raises(SuperharnessError):
        raise OperationError("nope", exit_code=1)

    # Also: catching plain Exception must not incidentally swallow it as a
    # SystemExit (SystemExit does not subclass Exception, so this would be
    # a no-op assertion if SuperharnessError were wrongly based on
    # BaseException instead).
    assert issubclass(SuperharnessError, Exception)
    assert not issubclass(SuperharnessError, SystemExit)


def test_contract_module_raises_instead_of_exiting():
    """Calling contract.main() directly (in-process, bypassing the
    __main__ guard) on a bad invocation must raise a SuperharnessError, not
    SystemExit — proving the sys.exit() call was moved out of the library
    code and now only lives at the CLI boundary."""
    with pytest.raises(SuperharnessError) as exc_info:
        contract.main(["task_exists"])  # missing --file/--task
    assert exc_info.value.exit_code == 1


def test_contract_subprocess_still_exits_1_on_bad_invocation():
    """The __main__ guard still translates that same raise into the exact
    exit code and stderr text a real `python -m superharness.engine.contract`
    invocation produced before this refactor."""
    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.contract", "task_exists"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )
    assert r.returncode == 1
    assert "--file and --task are required" in r.stderr


def test_contract_parse_failure_exits_1_with_message(tmp_path):
    """latest_handoff_task's parse-failure site (contract.py, formerly
    `sys.exit(f"Failed to parse handoff {file}: {e}")`) is not inside
    main() — it is a raise from deeper library code, propagating through
    main() unmodified up to the __main__ guard. Confirms that path keeps
    its exit code and message too, not just the argparse-usage sites."""
    handoff_dir = tmp_path / "handoffs"
    handoff_dir.mkdir()
    bad = handoff_dir / "bad.yaml"
    bad.write_text("not: valid: yaml: [")
    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.contract", "latest_handoff_task",
         "--dir", str(handoff_dir), "--to", "someone"],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        check=False,
    )
    assert r.returncode == 1
    assert "Failed to parse handoff" in r.stderr


def test_operator_start_already_running_exits_0_via_cli(tmp_path):
    """engine/operator.py's one in-process sys.exit() site (Operator
    already running) is caught by cli.py's operator_start handler and
    still produces the exact old behaviour: exit 0, the "already running"
    message on stderr."""
    import json
    import os

    from click.testing import CliRunner

    from superharness.cli import main
    from superharness.engine.operator import _OPERATOR_STATE_FILE

    (tmp_path / ".superharness").mkdir()
    state_file = tmp_path / _OPERATOR_STATE_FILE
    state_file.write_text(json.dumps({"operator_pid": os.getpid(), "dashboard_port": 8787}))

    runner = CliRunner()
    result = runner.invoke(main, ["operator", "start", "--project", str(tmp_path), "--no-daemon"])

    assert result.exit_code == 0
    assert "already running" in result.stderr
