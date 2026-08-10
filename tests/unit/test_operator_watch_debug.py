"""Opt-in watcher diagnostics must make lifecycle ownership attributable."""

from __future__ import annotations

import logging
import os
import stat
import subprocess
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch


def _operator(tmp_path: Path):
    from superharness.engine.operator import Operator

    (tmp_path / ".superharness").mkdir()
    return Operator(tmp_path)


def test_watch_debug_logs_watcher_registration_fields(tmp_path, monkeypatch, caplog):
    """Debug mode records root, recursion policy, exclusions, and child PID."""
    monkeypatch.setenv("SUPERHARNESS_WATCH_DEBUG", "true")
    proc = MagicMock(pid=4242)
    caplog.set_level(logging.WARNING, logger="superharness.engine.operator")

    with patch("superharness.engine.operator.subprocess.Popen", return_value=proc):
        _operator(tmp_path)._spawn_watcher()

    message = "\n".join(record.getMessage() for record in caplog.records)
    assert "[watch-debug]" in message
    assert "component=operator-watcher" in message
    assert f"watched_root={tmp_path}" in message
    assert "mode=poll" in message
    assert "recursive=False" in message
    assert "__pycache__" in message
    assert f"pid={os.getpid()}" in message
    assert "child_pid=4242" in message
    assert "lifecycle=start" in message


def test_watch_debug_keeps_watcher_stdio_visible(tmp_path, monkeypatch):
    """Debug mode must not discard the child logs needed for diagnosis."""
    monkeypatch.setenv("SUPERHARNESS_WATCH_DEBUG", "1")
    proc = MagicMock(pid=4242)
    with patch("superharness.engine.operator.subprocess.Popen", return_value=proc) as popen:
        _operator(tmp_path)._spawn_watcher()

    assert popen.call_args.kwargs["stdout"] is None
    assert popen.call_args.kwargs["stderr"] is None


def test_watch_debug_disabled_keeps_watcher_stdio_quiet(tmp_path, monkeypatch):
    """The default preserves DEVNULL routing and makes no diagnostic noise."""
    monkeypatch.delenv("SUPERHARNESS_WATCH_DEBUG", raising=False)
    proc = MagicMock(pid=4242)
    with patch("superharness.engine.operator.subprocess.Popen", return_value=proc) as popen:
        _operator(tmp_path)._spawn_watcher()

    assert popen.call_args.kwargs["stdout"] is subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] is subprocess.DEVNULL


def test_install_script_normalizes_watch_debug_environment(tmp_path):
    """The generated plist receives only normalised opt-in debug state."""
    script = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "install-operator-service.sh"
    )
    project = tmp_path / "project"
    project.mkdir()
    expected_hash = hashlib.md5(str(project.resolve()).encode()).hexdigest()[:8]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, content in {
        "md5": f"#!/bin/sh\n[ \"$1\" = \"-q\" ] || exit 9\nprintf '{expected_hash}'\n",
        "launchctl": "#!/bin/sh\n[ \"$1\" = \"print\" ] && exit 1\nprintf '%s\\n' \"$*\" >> \"$TRACE_FILE\"\nexit 0\n",
        "python3": "#!/bin/sh\nexit 0\n",
    }.items():
        executable = fake_bin / name
        executable.write_text(content)
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)

    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SUPERHARNESS_WATCH_DEBUG": "YES",
        "TRACE_FILE": str(tmp_path / "launchctl.trace"),
    }
    result = subprocess.run(
        ["bash", str(script), str(project)], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    plist = tmp_path / "home" / "Library" / "LaunchAgents" / f"com.superharness.operator.{expected_hash}.plist"
    assert "<key>SUPERHARNESS_WATCH_DEBUG</key>\n        <string>1</string>" in plist.read_text()
    assert "bootstrap gui/" in (tmp_path / "launchctl.trace").read_text()
    assert 'launchctl print "gui/${UID_VALUE}/${LABEL}"' in script.read_text()


def test_install_script_uses_requested_runtime_without_checkout_pythonpath(tmp_path):
    """A packaged CLI pins launchd to its own runtime, not a checkout import."""
    script = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "install-operator-service.sh"
    )
    project = tmp_path / "project"
    project.mkdir()
    expected_hash = hashlib.md5(str(project.resolve()).encode()).hexdigest()[:8]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for name, content in {
        "md5": f"#!/bin/sh\n[ \"$1\" = \"-q\" ] || exit 9\nprintf '{expected_hash}'\n",
        "launchctl": "#!/bin/sh\n[ \"$1\" = \"print\" ] && exit 1\nexit 0\n",
        "python3": "#!/bin/sh\nexit 0\n",
    }.items():
        executable = fake_bin / name
        executable.write_text(content)
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    requested_python = tmp_path / "packaged-python"
    requested_python.write_text("#!/bin/sh\nexit 0\n")
    requested_python.chmod(requested_python.stat().st_mode | stat.S_IXUSR)

    result = subprocess.run(
        ["bash", str(script), str(project)],
        env={
            "HOME": str(tmp_path / "home"),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "SUPERHARNESS_OPERATOR_PYTHON_BIN": str(requested_python),
        },
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    plist = (
        tmp_path
        / "home"
        / "Library"
        / "LaunchAgents"
        / f"com.superharness.operator.{expected_hash}.plist"
    )
    plist_text = plist.read_text()
    assert f"<string>{requested_python}</string>" in plist_text
    assert "<key>PYTHONPATH</key>" not in plist_text


def test_watch_debug_logs_cleanup_for_a_reaped_watcher(tmp_path, monkeypatch, caplog):
    """Every registration has a cleanup record when the child is reaped."""
    monkeypatch.setenv("SUPERHARNESS_WATCH_DEBUG", "1")
    op = _operator(tmp_path)
    watcher = MagicMock(pid=4242, returncode=0)
    watcher.poll.return_value = 0
    op.processes["watcher"] = watcher
    op._watcher_last_spawn = os.times().elapsed
    caplog.set_level(logging.WARNING, logger="superharness.engine.operator")

    def stop_after_tick(_interval):
        op._stopping = True

    with (
        patch.object(op, "_kill_process"),
        patch("superharness.engine.operator.time.sleep", side_effect=stop_after_tick),
    ):
        op.monitor_and_recover(poll_interval=0)

    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "lifecycle=cleanup" in messages
    assert "child_pid=4242" in messages
