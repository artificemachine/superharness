"""Regression tests for #156 — operator stop must verify identity without
assuming module-form argv, and must not lose state or exit 0 on refusal.

Hermetic: tmp_path state files only; `subprocess.run` (the ps read) and
`os.kill` are monkeypatched — no real process is ever signalled and no real
operator state is touched. The launchd-label path is short-circuited (no
labels, no plist) so the PID-fallback path under test actually runs.
"""

from __future__ import annotations

import json
import signal
import sys
import time
from pathlib import Path

from click.testing import CliRunner

from superharness.engine import launchd_health

_PID = 999999


def _make_project(tmp_path):
    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    return project


def _write_state(project, state):
    state_file = project / ".superharness" / "operator-state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")
    return state_file


def _invoke_stop(monkeypatch, project, ps_command):
    """Run `shux operator stop -p <project>` with ps and os.kill neutered."""
    from superharness.cli import main

    kills: list[tuple[int, int]] = []

    def fake_kill(pid, sig):
        kills.append((pid, sig))

    class _FakePs:
        stdout = ps_command

    monkeypatch.setattr(launchd_health, "operator_labels_for_project", lambda p: [])
    monkeypatch.setattr(
        launchd_health,
        "plist_path_for_label",
        lambda label: project.parent / "no-such-operator.plist",
    )
    monkeypatch.setattr("superharness.cli.os.kill", fake_kill)
    monkeypatch.setattr(
        "superharness.cli.subprocess.run", lambda *args, **kwargs: _FakePs()
    )

    result = CliRunner().invoke(main, ["operator", "stop", "-p", str(project)])
    return result, kills


def test_shell_started_operator_is_stopped(tmp_path, monkeypatch):
    """An operator started via the `shux` console script (not module form)
    carries the nonce in argv and must be verified and signalled."""
    project = _make_project(tmp_path)
    nonce = "3f7a9c1e5b6d4e8fa0c1d2b3e4f50617"
    _write_state(
        project,
        {
            "operator_pid": _PID,
            "operator_started_at": 1753400000.0,
            "operator_nonce": nonce,
        },
    )
    ps_line = (
        f"/home/u/.local/bin/shux operator start -p {project.resolve()} "
        f"--operator-nonce {nonce}"
    )

    result, kills = _invoke_stop(monkeypatch, project, ps_line)

    assert kills == [(_PID, signal.SIGTERM)], (
        f"expected one SIGTERM to pid {_PID}, got {kills}; output: {result.output}"
    )
    assert "Sent SIGTERM" in result.output


def test_unknown_pid_refusal_keeps_operator_pid(tmp_path, monkeypatch):
    """A PID whose command line does not carry the nonce must not be
    signalled, the state must keep operator_pid/operator_started_at, and the
    command must exit non-zero (SystemExit(2) passes through the function's
    `except Exception` untouched)."""
    project = _make_project(tmp_path)
    state_file = _write_state(
        project,
        {
            "operator_pid": _PID,
            "operator_started_at": 1753400000.0,
            "operator_nonce": "deadbeefdeadbeefdeadbeefdeadbeef",
        },
    )

    result, kills = _invoke_stop(monkeypatch, project, "cat /tmp/random-file")

    assert kills == [], f"os.kill must not be called, got {kills}"
    assert result.exit_code != 0, (
        f"refusal must exit non-zero, got {result.exit_code}: {result.output}"
    )
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    assert persisted.get("operator_pid") == _PID
    assert "operator_started_at" in persisted


def test_module_form_still_stopped(tmp_path, monkeypatch):
    """Legacy guard preserved: an operator with no nonce in state is still
    verified by the old module-form command-line check."""
    project = _make_project(tmp_path)
    _write_state(
        project,
        {
            "operator_pid": _PID,
            "operator_started_at": 1753400000.0,
        },
    )
    ps_line = (
        f"/usr/bin/python3 -m superharness.cli operator start -p {project.resolve()}"
    )

    result, kills = _invoke_stop(monkeypatch, project, ps_line)

    assert kills == [(_PID, signal.SIGTERM)], (
        f"legacy module-form operator must still be stopped, got {kills}; "
        f"output: {result.output}"
    )


# ---------------------------------------------------------------------------
# Iteration 6 (R1/R2/R3): REAL start→stop lifecycle, end to end.
#
# Every test above is mocked at the ps/kill seam. None of them can see the
# three production defects:
#   R1 — the #156 re-exec copies sys.argv verbatim; with the default `-p .`
#        (or any unresolved/symlinked path) the daemon's ps command line
#        never contains the RESOLVED project path that operator_stop verifies
#        against → verified stop is impossible for a default invocation.
#   R2 — the nonce state write ran BEFORE the start_stack() singleton check,
#        so a duplicate `operator start` clobbered the running daemon's nonce.
#   R3 — operator_pid was stamped by the short-lived fork parent; the daemon
#        child never restamped, so stop SIGTERMs a dead/possibly-recycled pid.
#
# This test runs the real CLI in real subprocesses (no seams), through the
# `--no-daemon` monitor path, fully hermetic in tmp_path. `-p` is passed
# through a symlink so the stop identity check can only pass once the
# re-exec argv carries the RESOLVED project (R1).
# ---------------------------------------------------------------------------

import os
import subprocess

import pytest

from superharness.engine.operator import _OPERATOR_STATE_FILE


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


def _kill_stray_watchers(marker: str) -> None:
    """Best-effort: kill any inbox_watch child still referencing the project."""
    try:
        out = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
    except OSError:
        return
    for line in out.splitlines():
        if "superharness.commands.inbox_watch" in line and marker in line:
            try:
                os.kill(int(line.split(None, 1)[0].strip()), signal.SIGKILL)
            except (ValueError, OSError):
                pass


@pytest.mark.timeout(90)
def test_operator_lifecycle_real_start_stop_cycle(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    # Pass -p through a symlink: only an argv that carries the RESOLVED
    # project can ever satisfy operator_stop's identity verification.
    alt = tmp_path / "alt"
    alt.symlink_to(project)
    resolved = project.resolve()
    state_file = project / _OPERATOR_STATE_FILE
    env = dict(os.environ)

    popen = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "superharness",
            "operator",
            "start",
            "-p",
            str(alt),
            "--no-daemon",
        ],
        cwd=str(project),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    try:
        state = None
        deadline = time.time() + 10.0
        while time.time() < deadline:
            rc = popen.poll()
            assert rc is None, (
                f"operator start exited early with rc={rc}; output:\n"
                f"{popen.stdout.read() if popen.stdout else ''}"
            )
            if state_file.is_file():
                try:
                    candidate = json.loads(state_file.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    candidate = None
                if (
                    isinstance(candidate, dict)
                    and candidate.get("operator_pid") == popen.pid
                    and candidate.get("operator_nonce")
                    and _pid_alive(popen.pid)
                ):
                    state = candidate
                    break
            time.sleep(0.2)
        assert state is not None, (
            "operator never stamped state with its own pid + nonce within 10s "
            f"(expected operator_pid=={popen.pid} and operator_nonce in "
            f"{state_file})"
        )

        stop = subprocess.run(
            [sys.executable, "-m", "superharness", "operator", "stop", "-p", str(project)],
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
            cwd=str(tmp_path),
        )
        assert stop.returncode == 0, (
            f"verified stop must exit 0, got {stop.returncode}\n"
            f"stdout:\n{stop.stdout}\nstderr:\n{stop.stderr}"
        )
        assert "Refusing" not in stop.stdout, (
            f"stop must not refuse a verified operator: {stop.stdout}"
        )

        popen.wait(timeout=10)

        final = {}
        if state_file.is_file():
            try:
                final = json.loads(state_file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                final = {}
        live_pid = final.get("operator_pid")
        assert not (live_pid and _pid_alive(int(live_pid))), (
            "state must not retain a live operator_pid after stop, "
            f"got {live_pid!r}"
        )
    finally:
        if popen.poll() is None:
            popen.kill()
            popen.wait(timeout=10)
        _kill_stray_watchers(str(resolved))
        _kill_stray_watchers(str(alt))


# ---------------------------------------------------------------------------
# Iteration 6 (R1, unit level): the re-exec argv itself.
#
# `python -m superharness operator start` WITHOUT -p (cwd = project) must
# still re-exec with an argv that operator_stop can verify: the RESOLVED
# project must be present as `--project <resolved>` (or as the replaced -p
# value), next to the nonce. execv is captured, never executed; a process
# that already carries --operator-nonce must never re-exec a second time.
# ---------------------------------------------------------------------------


def test_default_project_flag_verifiable(tmp_path, monkeypatch):
    import superharness.cli as cli_mod
    from superharness.cli import main
    from superharness.engine.operator import Operator

    project = tmp_path / "proj"
    project.mkdir()
    expected_project = str(Path(str(project)).resolve())

    captured: list[tuple[str, list[str]]] = []

    def fake_execv(exe, argv):
        captured.append((exe, list(argv)))
        raise SystemExit(0)  # real execv never returns; stop the call here

    monkeypatch.chdir(project)
    monkeypatch.setattr(cli_mod.os, "execv", fake_execv)
    # Never let the in-process invocation touch real engine seams.
    monkeypatch.setattr(sys, "argv", ["shux", "operator", "start"])
    monkeypatch.setattr(
        cli_mod, "_resume_installed_operator", lambda *a, **k: False
    )
    monkeypatch.setattr(Operator, "start_stack", lambda self, **kw: None)
    monkeypatch.setattr(Operator, "monitor_and_recover", lambda self, **kw: None)

    CliRunner().invoke(main, ["operator", "start", "--no-daemon"])

    assert len(captured) == 1, (
        f"expected exactly one re-exec, got {captured!r}"
    )
    exe, argv = captured[0]
    assert exe == sys.executable
    assert "--operator-nonce" in argv, f"nonce missing from {argv!r}"
    nonce = argv[argv.index("--operator-nonce") + 1]
    assert nonce and argv.count("--operator-nonce") == 1
    assert "--project" in argv, (
        "the re-exec argv must carry the resolved project so operator_stop "
        f"can verify it, got {argv!r}"
    )
    assert argv[argv.index("--project") + 1] == expected_project, (
        f"--project value must be the RESOLVED project {expected_project!r}, "
        f"got {argv!r}"
    )
    assert argv[1 : 1 + len(sys.argv)] == sys.argv, (
        "the original invocation argv must be preserved verbatim in the "
        "re-exec (only the -p/--project VALUE is rewritten, per R1)"
    )

    # Already-tagged process: no second exec, ever.
    result = CliRunner().invoke(
        main,
        [
            "operator", "start", "--no-daemon",
            "--operator-nonce", "ab" * 16,
        ],
    )
    assert result.exit_code == 0, result.output
    assert len(captured) == 1, (
        "a process already carrying --operator-nonce must not re-exec again"
    )
