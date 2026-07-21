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

Iteration 7 finishes the migration for the three remaining engine/ modules:
discussion.py (38 sites), inbox.py (23), discuss.py (8). Both discussion.py
and discuss.py have functions genuinely called in-process, not just via
subprocess: commands/discuss.py imports cmd_submit_round/cmd_close from
engine.discussion and cmd_status/cmd_approve from engine.discuss, so it
gained its own try/except SuperharnessError boundary at its own __main__
guard. commands/discussion_dispatch.py's deadline-exceeded path calls
engine.discussion.cmd_close in-process too, but it already had a bare
`except Exception` around that call — since SuperharnessError is a plain
Exception subclass (unlike SystemExit, which is not), that existing catch
now works correctly without any change. Before this iteration, that call
site had a real latent bug: sys.exit() inside cmd_close raised SystemExit,
which is not caught by `except Exception` at all, so a discussion closing
via the watcher's automatic deadline path could have taken the whole
watcher process down with it. inbox.py had no main() function at all —
its entire CLI was inline script code under `if __name__ == "__main__":` —
so migrating it required extracting that block into a real main(argv)
first, the same shape every other engine/ CLI module already has.
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


# ---------------------------------------------------------------------------
# Iteration 7 — discussion.py, inbox.py, discuss.py
# ---------------------------------------------------------------------------


def test_no_sys_exit_remains_in_engine():
    """The three modules iteration 7 migrated must have zero occurrences —
    not just a lowered total. This pinpoints regressions to the exact file,
    where the source-ratchet's engine-wide total would only say "something
    grew"."""
    import re
    from pathlib import Path as _Path

    engine_root = _Path(__file__).resolve().parents[3] / "src" / "superharness" / "engine"
    for name in ("discussion.py", "inbox.py", "discuss.py"):
        text = (engine_root / name).read_text()
        count = len(re.findall(r"sys\.exit", text))
        assert count == 0, f"{name} still contains {count} sys.exit occurrence(s)"


def test_discussion_exit_codes_preserved():
    """Parity sample across the three migrated modules' subprocess CLI
    boundaries: usage errors, a not-found domain error, and a rc-propagation
    site all still produce the same exit code and stderr text as before the
    migration to raise/handle_cli_error."""
    # engine/discussion.py: missing required flag (was `sys.exit("--topic is required")`)
    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.discussion", "start", "--discussions-dir", "/tmp/x"],
        capture_output=True, text=True, cwd=_REPO_ROOT, check=False,
    )
    assert r.returncode == 1
    assert "--topic is required" in r.stderr

    # engine/discussion.py: unknown discussion (was `sys.exit(f"Discussion not found: ...")`)
    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.discussion", "status",
         "--discussion-dir", "/tmp/does-not-exist/.superharness/discussions/nope"],
        capture_output=True, text=True, cwd=_REPO_ROOT, check=False,
    )
    assert r.returncode == 1
    assert "Discussion not found" in r.stderr

    # engine/discuss.py: missing required flags (was `print(...); sys.exit(1)`)
    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.discuss", "status"],
        capture_output=True, text=True, cwd=_REPO_ROOT, check=False,
    )
    assert r.returncode == 1
    assert "--handoff-dir is required" in r.stderr

    # engine/inbox.py: unrecognized command falls through to the catch-all
    # (was `print(...); sys.exit(1)`)
    inbox_file = str(_REPO_ROOT / "does-not-exist" / "inbox.yaml")
    r = subprocess.run(
        [PYTHON, "-m", "superharness.engine.inbox", "not-a-real-command", "--file", inbox_file],
        capture_output=True, text=True, cwd=_REPO_ROOT, check=False,
    )
    assert r.returncode == 1
    assert "not fully implemented" in r.stderr


def test_watcher_survives_a_discussion_error(tmp_path, monkeypatch):
    """The REAL engine.discussion.cmd_close, called on the watcher's own
    deadline-exceeded auto-close path (commands/discussion_dispatch.py:
    dispatch), must not escape dispatch() when it hits a "Discussion not
    found" error.

    This is the concrete regression this iteration closes: before the
    migration, cmd_close's `sys.exit(f"Discussion not found: ...")` raised
    SystemExit, which is NOT a subclass of Exception, so the pre-existing
    `except Exception as _ce:` around that call site (discussion_dispatch.py)
    did not catch it — a discussion failing to close via the watcher's
    automatic deadline path could have taken the whole watcher process down.
    SuperharnessError IS an Exception subclass, so that same pre-existing
    except clause now works correctly, with no change needed to
    discussion_dispatch.py or inbox_watch.py themselves. The status lookup
    is faked (it goes through a real subprocess otherwise) and, as a side
    effect, deletes the discussion's SQLite row right before the deadline
    check — simulating a race with a concurrent close — so cmd_close's own
    discussions_dao.get() lookup comes back empty and it takes its own
    genuine not-found path, rather than one manufactured directly by the
    test. The discussion is deliberately seeded first so dispatch()'s outer
    `discussions_dao.get_all(conn, status="active")` scan finds it and
    reaches the deadline-exceeded branch at all.
    """
    import json
    from datetime import datetime, timedelta, timezone

    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    project = tmp_path
    sh = project / ".superharness"
    sh.mkdir(parents=True)
    discussions_dir = sh / "discussions"
    discussions_dir.mkdir()

    disc_id = "discuss-20260101T000000Z-test"
    disc_dir = discussions_dir / disc_id
    disc_dir.mkdir()

    old_time = (datetime.now(timezone.utc) - timedelta(minutes=35)).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection(str(project))
    init_db(conn)
    discussions_dao.create(
        conn, id=disc_id, topic="old discussion", owners=["claude-code", "gemini-cli"],
        max_rounds=2, now=old_time,
    )
    conn.commit()
    conn.close()

    def _fake_run_engine(args):
        # Only the "status" lookup happens before the deadline check; faked
        # so this test doesn't depend on a real subprocess round-trip.
        assert args[0] == "status"
        # Simulate a concurrent close: the row cmd_close will look up is
        # gone by the time it runs, so it takes its own real not-found path.
        _conn = get_connection(str(project))
        _conn.execute("DELETE FROM discussions WHERE id = ?", (disc_id,))
        _conn.commit()
        _conn.close()
        payload = {
            "id": disc_id,
            "status": "active",
            "current_round": 1,
            "participants": ["claude-code", "gemini-cli"],
            "topic": "old discussion",
            "created_at": old_time,
        }
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(
        "superharness.commands.discussion_dispatch._run_engine", _fake_run_engine
    )

    from superharness.commands.discussion_dispatch import dispatch

    # Must complete the tick and return normally — not propagate — even
    # though the real cmd_close raises for this now-vanished discussion.
    dispatch(str(project))
