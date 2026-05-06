"""TDD tests for 3 bugs that left orphaned LaunchAgents and misleading logs:

Bug A: session-start.sh auto-installs a LaunchAgent whenever a .superharness/
       dir exists. Tests that exercise session-start.sh against a pytest
       tmp_path leave behind a real launchd plist pointing at the (later
       deleted) temp dir. session-start.sh must respect
       SUPERHARNESS_NO_AUTO_INSTALL=1 so test runs cannot pollute the system.

Bug B: daemon.py:106 logs every watcher exit as "crashed (rc=N)" — even
       when rc=0 (clean exit). The log must distinguish clean exits from
       crashes.

Bug C: service_installer._install_launchd swallows install-script failures
       silently — it returns False but prints nothing, so users see
       "Watcher worker is ready" with no indication the install failed.
       The installer must surface install-script failures on stderr.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent


# ---------------------------------------------------------------------------
# Bug A — session-start.sh must skip launchd auto-install under
# SUPERHARNESS_NO_AUTO_INSTALL=1
# ---------------------------------------------------------------------------

def test_session_start_skips_launchd_when_no_auto_install_set(tmp_path):
    """session-start.sh must NOT invoke ensure-launchd-inbox-watcher.sh
    when SUPERHARNESS_NO_AUTO_INSTALL=1 is set in the environment.

    Strategy: read the script's source — when the env var is set, the call
    to ensure-launchd-inbox-watcher.sh must be guarded.
    """
    script = REPO_ROOT / "adapters" / "claude-code" / "hooks" / "session-start.sh"
    src = script.read_text()
    assert "SUPERHARNESS_NO_AUTO_INSTALL" in src, (
        "session-start.sh must check SUPERHARNESS_NO_AUTO_INSTALL env var "
        "to allow tests to opt out of LaunchAgent installation. "
        "Without this, every test run that exercises session-start.sh "
        "with a tmp .superharness/ dir leaves an orphaned plist on the "
        "user's machine."
    )


def test_session_start_no_launchctl_when_opt_out(tmp_path, monkeypatch):
    """Run session-start.sh end-to-end with SUPERHARNESS_NO_AUTO_INSTALL=1
    and verify the ensure-launchd script is not invoked.

    We replace launchctl on PATH with a sentinel that records calls; if
    session-start.sh transitively invokes launchctl, the sentinel file is
    written.
    """
    project = tmp_path / "proj"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: test\n")

    fake_bin = tmp_path / "fakebin"
    fake_bin.mkdir()
    sentinel = tmp_path / "launchctl_called"
    fake_launchctl = fake_bin / "launchctl"
    fake_launchctl.write_text(f'#!/bin/bash\necho "$@" >> "{sentinel}"\nexit 0\n')
    fake_launchctl.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH','')}"
    env["SUPERHARNESS_NO_AUTO_INSTALL"] = "1"

    script = REPO_ROOT / "adapters" / "claude-code" / "hooks" / "session-start.sh"
    subprocess.run(
        ["bash", str(script)], cwd=str(project), env=env,
        capture_output=True, text=True, check=False, timeout=10,
    )

    assert not sentinel.exists(), (
        f"launchctl was invoked despite SUPERHARNESS_NO_AUTO_INSTALL=1. "
        f"Calls: {sentinel.read_text() if sentinel.exists() else '<none>'}"
    )


# ---------------------------------------------------------------------------
# Bug B — daemon log must not call rc=0 a "crash"
# ---------------------------------------------------------------------------

def test_daemon_log_distinguishes_clean_exit_from_crash():
    """daemon.py monitor script must log rc=0 as a clean exit, not a crash."""
    daemon_py = REPO_ROOT / "src" / "superharness" / "commands" / "daemon.py"
    src = daemon_py.read_text()
    # The monitor script template must branch on exit code, not log every
    # exit as a crash.
    has_branch = (
        "if exit_code == 0" in src
        or "if exit_code != 0" in src
        or "exited cleanly" in src
    )
    assert has_branch, (
        "daemon.py monitor script logs every watcher exit as "
        "'crashed (rc=N)' — including rc=0 (clean exit). The log message "
        "must branch on exit_code so rc=0 reads as a clean exit, not a crash."
    )


# ---------------------------------------------------------------------------
# Bug C — service_installer must surface install failures on stderr
# ---------------------------------------------------------------------------

def test_install_launchd_prints_error_on_failure(tmp_path, capsys, monkeypatch):
    """_install_launchd must print to stderr when the install script fails,
    not silently return False — otherwise users see 'Watcher worker is ready'
    with no indication the install actually failed."""
    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        from superharness.engine import service_installer
    finally:
        if str(REPO_ROOT / "src") in sys.path:
            sys.path.remove(str(REPO_ROOT / "src"))

    # Create a fake scripts dir with a failing install script
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    fail_script = scripts_dir / "install-launchd-inbox-watcher.sh"
    fail_script.write_text("#!/bin/bash\necho 'simulated install failure' >&2\nexit 7\n")
    fail_script.chmod(0o755)

    project = tmp_path / "proj"
    project.mkdir()
    worker = tmp_path / "worker"
    worker.mkdir()

    ok = service_installer._install_launchd(
        project_dir=project, worker_dir=worker, scripts_dir=scripts_dir,
        interval=15, recover_timeout=3, recover_action="retry",
        launcher_timeout=180, to="both", codex_bypass=False,
    )

    captured = capsys.readouterr()
    assert ok is False
    assert (
        "fail" in captured.err.lower()
        or "exit code" in captured.err.lower()
        or "rc=" in captured.err.lower()
        or "returncode" in captured.err.lower()
    ), (
        f"_install_launchd returned False but printed nothing useful to stderr. "
        f"Users get 'Watcher worker is ready' but no actual install. "
        f"stderr was: {captured.err!r}"
    )
