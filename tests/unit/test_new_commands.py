"""Smoke tests for S6+S7+S8 new Python command modules."""
from __future__ import annotations

import subprocess
import sys

import pytest


def _help_exits_zero(module):
    with pytest.raises(SystemExit) as exc:
        module.main(["--help"])
    assert exc.value.code == 0


def test_inbox_enqueue_help():
    from superharness.commands import inbox_enqueue
    _help_exits_zero(inbox_enqueue)


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_inbox_normalize_help():
    from superharness.commands import inbox_normalize
    _help_exits_zero(inbox_normalize)


def test_inbox_recover_help():
    from superharness.commands import inbox_recover
    _help_exits_zero(inbox_recover)


def test_install_wrapper_help():
    from superharness.commands import install_wrapper
    _help_exits_zero(install_wrapper)


def test_doctor_help():
    from superharness.commands import doctor
    _help_exits_zero(doctor)


def test_uninstall_help():
    from superharness.commands import uninstall
    _help_exits_zero(uninstall)


def test_status_help():
    from superharness.commands import status
    _help_exits_zero(status)


def test_notify_help():
    from superharness.commands import notify
    _help_exits_zero(notify)


def test_init_project_help():
    from superharness.commands import init_project
    _help_exits_zero(init_project)


def test_heartbeat_help():
    from superharness.commands import heartbeat
    _help_exits_zero(heartbeat)


def test_demo_help():
    from superharness.commands import demo
    _help_exits_zero(demo)


def test_watcher_worker_help():
    from superharness.commands import watcher_worker
    _help_exits_zero(watcher_worker)


def test_superharness_main_help():
    import os
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    env = {**__import__("os").environ, "PYTHONPATH": os.path.join(repo_root, "src")}
    result = subprocess.run(
        [sys.executable, "-m", "superharness", "--help"],
        capture_output=True,
        text=True,
        cwd=repo_root,
        env=env,
    )
    assert result.returncode == 0, f"--help failed:\n{result.stdout}\n{result.stderr}"
    assert "superharness" in result.stdout
