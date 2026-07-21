"""TDD tests for 3 bugs that left orphaned LaunchAgents and misleading logs,
plus (PLAN-superharness-L5.md iteration 5) a session-scoped leak guard:

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

TestNoLaunchdLabelLeaks: a real leak was found live on 2026-07-12 — a
`com.superharness.inbox.worker-proj` job pointing at a deleted pytest
tmp dir, left behind by a pre-rewrite watcher-install test that ran the
real install script without the fake-launchctl pattern (Bug A's own
guard didn't cover this specific test-writing mistake). This class
generalizes the check: no test run may leave a NEW com.superharness.*
label behind, whatever the cause.
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
    """The daemon monitor must log rc=0 as a clean exit, not a crash.

    Iteration 3 of PLAN-coding-practices.md moved the monitor loop (and this
    log message) out of daemon.py's generated-script string into a real
    module, commands/daemon_monitor.py — updated to read from there.
    """
    daemon_monitor_py = REPO_ROOT / "src" / "superharness" / "commands" / "daemon_monitor.py"
    src = daemon_monitor_py.read_text()
    # The monitor must branch on exit code, not log every exit as a crash.
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


# ---------------------------------------------------------------------------
# TestNoLaunchdLabelLeaks — PLAN-superharness-L5.md iteration 5
# ---------------------------------------------------------------------------

class TestNoLaunchdLabelLeaks:
    def test_leaked_label_detected(self):
        before = {"com.superharness.inbox.myproject", "com.apple.something"}
        after = before | {"com.superharness.inbox.tmpXYZ"}
        assert find_leaked_labels(before, after) == {"com.superharness.inbox.tmpXYZ"}

    def test_preexisting_labels_ignored(self):
        before = {"com.superharness.inbox.myproject", "com.apple.something"}
        after = set(before)
        assert find_leaked_labels(before, after) == set()

    def test_all_watcher_install_tests_use_fake_launchctl(self):
        """Static audit: every test in test_install_scripts.py that runs the
        real launchd/systemd install script or watcher_worker must route
        launchctl through a fake PATH entry (the _fake_launchd_bin pattern)
        or mock the service installer — never invoke the real launchctl."""
        install_tests = REPO_ROOT / "tests" / "unit" / "test_install_scripts.py"
        src = install_tests.read_text()
        import re
        # Split into individual test function bodies.
        funcs = re.split(r"\ndef (test_\w+)", src)[1:]
        offenders = []
        for name, body in zip(funcs[0::2], funcs[1::2]):
            invokes_install = (
                "install-launchd-inbox-watcher.sh" in body
                or "watcher_worker" in body
                or "_run_watcher_worker_py" in body
            )
            if not invokes_install:
                continue
            safe = (
                "_fake_launchd_bin" in body
                or "fakebin" in body
                or "fake_bin" in body
                or "mock" in body.lower()
                or "patch(" in body
            )
            if not safe:
                offenders.append(name)
        assert not offenders, (
            f"these tests invoke the real install script/watcher_worker without "
            f"faking launchctl, risking a leaked com.superharness.* launchd job: "
            f"{offenders}"
        )


def find_leaked_labels(before: set[str], after: set[str]) -> set[str]:
    """Return superharness launchd labels present in `after` but not `before`."""
    return {label for label in (after - before) if label.startswith("com.superharness.")}


@pytest.fixture(scope="module", autouse=True)
def _launchd_label_snapshot():
    """Session-scoped guard: fail the module if any test leaves a NEW
    com.superharness.* launchd label behind. Real regression test for the
    'worker-proj' leak found and removed live on 2026-07-12."""
    if sys.platform != "darwin" or not _has_launchctl():
        yield
        return
    before = _current_labels()
    yield
    after = _current_labels()
    leaked = find_leaked_labels(before, after)
    assert not leaked, (
        f"test run leaked launchd label(s): {leaked}. Check the newest test in "
        f"this file or test_install_scripts.py for a missing fake-launchctl PATH."
    )


def _has_launchctl() -> bool:
    import shutil
    return shutil.which("launchctl") is not None


def _current_labels() -> set[str]:
    try:
        result = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=10)
    except Exception:
        return set()
    labels = set()
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            labels.add(parts[-1])
    return labels
