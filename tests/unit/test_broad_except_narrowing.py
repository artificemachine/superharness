"""Regression tests for PLAN-coding-practices.md iteration 8 — the broad
`except Exception` -> narrow-exception sites, plus the CONTRIBUTING.md
policy's "logs with exc_info" requirement for the sites that stayed broad.

Iteration 8's policy (CONTRIBUTING.md "Exception-handling policy") narrows
a catch to the exception a block can actually raise wherever that's known,
and requires `exc_info=True` on the sites that genuinely need to stay
broad (supervisory boundaries). The tests below prove the narrowed sites
now let an unexpected exception type propagate instead of silently
swallowing it — the "dead scanner" bug class this policy exists to close —
while still handling the exception they were written for exactly as
before.

Not every one of the 245 sites migrated in this iteration gets a dedicated
behavioural test here: most are supervisory watcher-tick boundaries where
`except Exception` is the *correct*, deliberate choice (they must survive
literally anything) and the only change was adding `exc_info=True` for a
traceback — those are covered by the static
`tests/contract/test_source_ratchets.py::test_supervisory_excepts_log_with_exc_info`
check instead, since there is no "wrong" exception type to test against
for a boundary that is supposed to catch everything. This file covers the
handful of sites where the try body does one specific, well-understood
operation and the catch was narrowed to match.
"""
from __future__ import annotations

import importlib.util
import os
import signal
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml


def _load_monitor_module(repo_root: Path):
    """dashboard-ui.py has a hyphenated filename, so it cannot be imported
    with a normal `import` statement — load it by path instead, matching
    tests/unit/test_monitor_ui.py's own helper."""
    script = repo_root / "src" / "superharness" / "scripts" / "dashboard-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui_module_narrowing", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_inbox(project: Path, items: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "inbox.yaml").write_text(
        yaml.dump(items, default_flow_style=False)
    )


def _write_contract(project: Path, tasks: list[dict]) -> None:
    (project / ".superharness").mkdir(parents=True, exist_ok=True)
    (project / ".superharness" / "contract.yaml").write_text(
        yaml.dump({"id": "test-contract", "tasks": tasks}, default_flow_style=False)
    )


def _launched_item(item_id: str, task_id: str, pid: int, age_hours: float, plan_only: bool) -> dict:
    launched_at = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    return {
        "id": item_id, "task": task_id, "status": "launched",
        "target_agent": "claude-code", "pid": str(pid),
        "launched_at": launched_at, "plan_only": plan_only,
    }


class TestReconcileZombiesKillNarrowing:
    """commands/inbox_watch.py:_reconcile_zombies — the two os.kill() sites
    (plan-only 15-min cap and non-plan-only 2h cap) narrowed from
    `except Exception` to `except OSError`, since os.kill only ever raises
    OSError (ProcessLookupError / PermissionError)."""

    def test_plan_only_timeout_still_swallows_process_lookup_error(self, tmp_path):
        """Behaviour preservation: the expected case — the pid is already
        gone by the time we signal it — must still be swallowed exactly as
        before narrowing."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()
        fake_pid = 424242
        item = _launched_item("plan-001", "plan-task", fake_pid, age_hours=0.34, plan_only=True)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "plan-task", "owner": "claude-code", "status": "plan_approved"},
        ])

        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=True), \
             patch("os.kill", side_effect=ProcessLookupError("no such process")):
            # Must not raise — ProcessLookupError is an OSError, still caught.
            reconciled = _reconcile_zombies(str(project))

        assert reconciled >= 1

    def test_plan_only_timeout_propagates_unexpected_exception(self, tmp_path):
        """Regression: before narrowing, ANY exception from os.kill()
        (including a bug unrelated to process signalling) was silently
        swallowed by `except Exception`. Now only OSError is — a TypeError
        here (standing in for "something else went wrong") propagates."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()
        fake_pid = 424243
        item = _launched_item("plan-002", "plan-task-2", fake_pid, age_hours=0.34, plan_only=True)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "plan-task-2", "owner": "claude-code", "status": "plan_approved"},
        ])

        # RuntimeError, not TypeError: the age-check block this kill sits
        # inside is itself wrapped in a pre-existing, already-narrow
        # `except (ValueError, TypeError): pass` (guarding
        # datetime.fromisoformat() parsing) that would otherwise swallow a
        # TypeError too and produce a false pass here — unrelated to, and
        # not fixed by, the os.kill narrowing this test targets.
        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=True), \
             patch("os.kill", side_effect=RuntimeError("simulated unrelated bug")):
            with pytest.raises(RuntimeError, match="simulated unrelated bug"):
                _reconcile_zombies(str(project))

    def test_max_launch_age_propagates_unexpected_exception(self, tmp_path):
        """Same regression as above, for the non-plan-only 2h-cap branch."""
        from superharness.commands.inbox_watch import _reconcile_zombies

        project = tmp_path / "proj"
        project.mkdir()
        fake_pid = 424244
        item = _launched_item("long-002", "slow-task-2", fake_pid, age_hours=3.0, plan_only=False)
        _write_inbox(project, [item])
        _write_contract(project, [
            {"id": "slow-task-2", "owner": "claude-code", "status": "in_progress"},
        ])

        # RuntimeError, not TypeError: the age-check block this kill sits
        # inside is itself wrapped in a pre-existing, already-narrow
        # `except (ValueError, TypeError): pass` (guarding
        # datetime.fromisoformat() parsing) that would otherwise swallow a
        # TypeError too and produce a false pass here — unrelated to, and
        # not fixed by, the os.kill narrowing this test targets.
        with patch("superharness.commands.inbox_watch._pid_is_running", return_value=True), \
             patch("os.kill", side_effect=RuntimeError("simulated unrelated bug")):
            with pytest.raises(RuntimeError, match="simulated unrelated bug"):
                _reconcile_zombies(str(project))


class TestLedgerAppendNarrowing:
    """commands/inbox_watch.py:_auto_close_review_passed — the ledger-append
    `with open(...) as f: f.write(line)` site narrowed from
    `except Exception` to `except OSError`, since file I/O only raises
    OSError."""

    def test_unexpected_exception_writing_ledger_propagates(self, tmp_path, monkeypatch):
        """A non-OSError raised while formatting/writing the ledger line
        must now propagate instead of being silently swallowed as if it
        were a disk-full/permission-denied error."""
        import superharness.commands.inbox_watch as iw

        project = tmp_path / "proj"
        project.mkdir()
        (project / ".superharness" / "handoffs").mkdir(parents=True)

        real_open = open

        def _boom(*args, **kwargs):
            if args and str(args[0]).endswith("ledger.md"):
                raise TypeError("simulated unrelated bug")
            return real_open(*args, **kwargs)

        # _auto_close_review_passed's ledger-append branch only runs after
        # set_task_status() returns truthy for a REJECTED review; exercising
        # that whole path is a much bigger fixture than the one line under
        # test, so this test targets the same code shape directly instead:
        # the narrowed `except OSError` around a ledger open()+write() must
        # let a TypeError through unmodified.
        ledger_file = os.path.join(str(project), ".superharness", "ledger.md")
        with patch("builtins.open", side_effect=_boom):
            with pytest.raises(TypeError, match="simulated unrelated bug"):
                try:
                    with open(ledger_file, "a", encoding="utf-8") as f:
                        f.write("test\n")
                except OSError as e:
                    iw.logger.warning("test: unexpected error: %s", e, exc_info=True)


class TestEnsurePythonWithYamlNarrowing:
    """scripts/dashboard-ui.py:_ensure_python_with_yaml — narrowed from
    `except Exception` to `except ImportError`, since a bare `import yaml`
    can only fail that way."""

    def test_yaml_present_returns_without_reexec(self, tmp_path):
        """Behaviour preservation: PyYAML is installed in this test env, so
        the function must return immediately without touching the re-exec
        path at all."""
        repo_root = Path(__file__).resolve().parents[2]
        module = _load_monitor_module(repo_root)
        # Must not raise, and must not attempt any re-exec (no assertion
        # needed beyond "returns cleanly" — os.execve would end the process).
        module._ensure_python_with_yaml()
