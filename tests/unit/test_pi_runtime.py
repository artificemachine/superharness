"""Fixture-only tests for Pi's ephemeral JSONL runtime."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_POSIX_TERMINATION_SIGNALS = (
    (signal.SIGTERM, signal.SIGKILL) if os.name == "posix" else (signal.SIGTERM,)
)
_REQUIRES_POSIX_FIXTURE = pytest.mark.skipif(
    os.name != "posix",
    reason="Pi fixture launchers use POSIX shebang executables and delegate-to-pi.sh",
)

SUCCESS_LINES = (
    '{"type":"session","version":3,"id":"fixture-session"}\n'
    '{"type":"message_end","message":{"role":"assistant","content":'
    '[{"type":"text","text":"fixture result"}],"provider":"provider-a",'
    '"model":"model-a","usage":{},"cost":{},"stopReason":"stop"}}\n'
    '{"type":"agent_end","messages":[]}\n'
)
ERROR_LINES = (
    '{"type":"session","version":3,"id":"fixture-session-error"}\n'
    '{"type":"message_end","message":{"role":"assistant","content":[],"provider":'
    '"provider-a","model":"model-a","usage":{},"cost":{},"stopReason":"error",'
    '"errorMessage":"fixture failure"}}\n'
    '{"type":"agent_end","messages":[]}\n'
)
TOOL_SUCCESS_LINES = (
    '{"type":"session","version":3,"id":"fixture-session-tool"}\n'
    '{"type":"agent_start"}\n'
    '{"type":"turn_start"}\n'
    '{"type":"message_end","message":{"role":"assistant","content":'
    '[{"type":"toolCall","id":"fixture-call","name":"write",'
    '"arguments":{"path":"fixture.txt","content":"fixture\\n"}}],'
    '"usage":{"input":10,"output":2},"cost":{"total":0.001},'
    '"stopReason":"toolUse"}}\n'
    '{"type":"tool_execution_start","toolCallId":"fixture-call",'
    '"toolName":"write","args":{}}\n'
    '{"type":"tool_execution_end","toolCallId":"fixture-call",'
    '"toolName":"write","result":{},"isError":false}\n'
    '{"type":"message_end","message":{"role":"toolResult",'
    '"toolCallId":"fixture-call","toolName":"write","content":[], '
    '"isError":false}}\n'
    '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}\n'
    '{"type":"turn_start"}\n'
    '{"type":"message_end","message":{"role":"assistant","content":'
    '[{"type":"text","text":"fixture complete"}],'
    '"usage":{"input":20,"output":3},"cost":{"total":0.002},'
    '"stopReason":"stop"}}\n'
    '{"type":"turn_end","message":{"role":"assistant"},"toolResults":[]}\n'
    '{"type":"agent_end","messages":[]}\n'
)


def _runtime():
    from superharness.engine import pi_runtime

    return pi_runtime


def _dispatch_runtime():
    from superharness.commands import inbox_dispatch

    return inbox_dispatch


def _write_fake_pi(tmp_path: Path) -> tuple[Path, Path]:
    """Create a fake executable that records argv/cwd and emits env-provided JSONL."""
    fake_pi = tmp_path / "pi"
    record = tmp_path / "pi-record.json"
    fake_pi.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys, time\n"
        "record = os.environ.get('PI_RECORD')\n"
        "if record:\n"
        "    with open(record, 'w', encoding='utf-8') as stream:\n"
        "        json.dump({'argv': sys.argv[1:], 'cwd': os.getcwd()}, stream)\n"
        "self_record = os.environ.get('PI_SELF_PID')\n"
        "if self_record:\n"
        "    with open(self_record, 'w', encoding='utf-8') as stream:\n"
        "        stream.write(str(os.getpid()))\n"
        "descendant_record = os.environ.get('PI_DESCENDANT_PID')\n"
        "if descendant_record:\n"
        "    child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "    with open(descendant_record, 'w', encoding='utf-8') as stream:\n"
        "        stream.write(str(child.pid))\n"
        "ready = os.environ.get('PI_READY')\n"
        "if ready:\n"
        "    with open(ready, 'w', encoding='utf-8') as stream:\n"
        "        stream.write('ready')\n"
        "time.sleep(float(os.environ.get('PI_SLEEP', '0')))\n"
        "sys.stdout.write(os.environ.get('PI_FIXTURE', ''))\n"
        "sys.stdout.flush()\n"
        "sys.stderr.write(os.environ.get('PI_STDERR', ''))\n"
        "raise SystemExit(int(os.environ.get('PI_EXIT', '0')))\n",
        encoding="utf-8",
    )
    fake_pi.chmod(0o755)
    return fake_pi, record


def _run_fake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture: str,
    *,
    exit_code: int = 0,
    sleep: float = 0,
    timeout: float = 2,
) -> tuple[int, dict]:
    runtime = _runtime()
    fake_pi, record = _write_fake_pi(tmp_path)
    monkeypatch.setenv("PI_RECORD", str(record))
    monkeypatch.setenv("PI_FIXTURE", fixture)
    monkeypatch.setenv("PI_EXIT", str(exit_code))
    monkeypatch.setenv("PI_SLEEP", str(sleep))
    rc = runtime.run_pi(
        "one prompt argument\nwith a newline",
        model="provider-a/model-a",
        effort="medium",
        pi_binary=str(fake_pi),
        timeout_seconds=timeout,
    )
    data = json.loads(record.read_text()) if record.exists() else {}
    return rc, data


def test_build_command_is_ephemeral_json_print_mode() -> None:
    command = _runtime().build_command(
        "line one\nline two", model="provider-a/model-a", effort="high"
    )

    assert command == [
        "pi",
        "--mode",
        "json",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--model",
        "provider-a/model-a",
        "--thinking",
        "high",
        "-p",
        "line one\nline two",
    ]
    assert command.count("line one\nline two") == 1
    assert "--no-context-files" not in command


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh"])
def test_supported_effort_maps_directly(effort: str) -> None:
    command = _runtime().build_command("prompt", effort=effort)
    assert command[command.index("--thinking") + 1] == effort


def test_effort_max_maps_to_supported_thinking_level() -> None:
    command = _runtime().build_command("prompt", effort="max")
    assert command[command.index("--thinking") + 1] == "xhigh"


@_REQUIRES_POSIX_FIXTURE
def test_session_header_is_accepted_and_stream_is_forwarded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, record = _run_fake(tmp_path, monkeypatch, SUCCESS_LINES)

    assert rc == 0
    assert capsys.readouterr().out == SUCCESS_LINES
    assert record["argv"].count("one prompt argument\nwith a newline") == 1


@_REQUIRES_POSIX_FIXTURE
def test_assistant_error_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, _ = _run_fake(tmp_path, monkeypatch, ERROR_LINES)
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == ERROR_LINES
    assert "fixture failure" in captured.err


@pytest.mark.parametrize(
    "terminal",
    [
        (
            '{"type":"message_end","message":{"role":"assistant","content":[],'
            '"stopReason":"error"}}\n'
        ),
        (
            '{"type":"message_end","message":{"role":"assistant","content":[],'
            '"stopReason":"stop","errorMessage":"embedded failure"}}\n'
        ),
    ],
)
@_REQUIRES_POSIX_FIXTURE
def test_each_assistant_error_signal_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    terminal: str,
) -> None:
    fixture = (
        '{"type":"session","version":3,"id":"fixture"}\n'
        + terminal
        + '{"type":"agent_end","messages":[]}\n'
    )
    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)
    assert rc != 0


@pytest.mark.parametrize(
    "fixture",
    [
        (
            '{"type":"session","version":3,"id":"fixture"}\n'
            '{"type":"agent_end","messages":[]}\n'
        ),
        '{"type":"session","version":3,"id":"fixture"}\n',
    ],
)
@_REQUIRES_POSIX_FIXTURE
def test_missing_terminal_event_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fixture: str,
) -> None:
    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)
    assert rc != 0


@_REQUIRES_POSIX_FIXTURE
def test_truncated_stream_without_agent_end_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, _ = _run_fake(tmp_path, monkeypatch, SUCCESS_LINES.rsplit("\n", 2)[0] + "\n")
    assert rc != 0


@_REQUIRES_POSIX_FIXTURE
def test_malformed_json_returns_nonzero_and_is_forwarded_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = '{"type":"session"}\n{not-json}\n'
    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)
    captured = capsys.readouterr()
    assert rc != 0
    assert captured.out == fixture


@_REQUIRES_POSIX_FIXTURE
def test_tool_using_turn_with_multiple_assistant_messages_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc, _ = _run_fake(tmp_path, monkeypatch, TOOL_SUCCESS_LINES)

    assert rc == 0
    assert capsys.readouterr().out == TOOL_SUCCESS_LINES


@_REQUIRES_POSIX_FIXTURE
def test_multiple_intermediate_tool_use_messages_succeed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_use = (
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"stopReason":"toolUse"}}\n'
    )
    terminal = (
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"stopReason":"stop"}}\n'
    )
    fixture = (
        '{"type":"session","version":3,"id":"fixture"}\n'
        + tool_use
        + tool_use
        + terminal
        + '{"type":"agent_end","messages":[]}\n'
    )

    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)

    assert rc == 0


@pytest.mark.parametrize(
    ("stop_reason_field", "expected_error"),
    [
        ('"stopReason":"toolUse"', "terminal-success"),
        ("", "stopReason is missing"),
        ('"stopReason":"futureReason"', "unsupported assistant stopReason"),
        ('"stopReason":"aborted"', "assistant aborted"),
        ('"stopReason":"error"', "assistant stopReason was error"),
    ],
)
@_REQUIRES_POSIX_FIXTURE
def test_nonterminal_assistant_message_cannot_end_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    stop_reason_field: str,
    expected_error: str,
) -> None:
    separator = "," if stop_reason_field else ""
    fixture = (
        '{"type":"session","version":3,"id":"fixture"}\n'
        '{"type":"message_end","message":{"role":"assistant","content":[]'
        f"{separator}{stop_reason_field}}}}}\n"
        '{"type":"agent_end","messages":[]}\n'
    )

    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)

    assert rc != 0
    assert expected_error in capsys.readouterr().err


@_REQUIRES_POSIX_FIXTURE
def test_length_is_a_terminal_success_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = (
        '{"type":"session","version":3,"id":"fixture"}\n'
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"stopReason":"length"}}\n'
        '{"type":"agent_end","messages":[]}\n'
    )

    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)

    assert rc == 0


@_REQUIRES_POSIX_FIXTURE
def test_duplicate_terminal_success_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    terminal = (
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"stopReason":"stop"}}\n'
    )
    fixture = (
        '{"type":"session","version":3,"id":"fixture"}\n'
        + terminal
        + terminal
        + '{"type":"agent_end","messages":[]}\n'
    )

    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)

    assert rc != 0
    assert "duplicate terminal-success" in capsys.readouterr().err


@_REQUIRES_POSIX_FIXTURE
def test_event_after_agent_end_returns_nonzero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = SUCCESS_LINES + '{"type":"turn_start"}\n'

    rc, _ = _run_fake(tmp_path, monkeypatch, fixture)

    assert rc != 0
    assert "followed agent_end" in capsys.readouterr().err


def test_protocol_failure_is_sticky() -> None:
    parser = _runtime().PiEventParser()
    parser.feed(
        '{"type":"message_end","message":{"role":"assistant","content":[]}}\n'
    )
    initial_failure = parser.finish()
    parser.feed(
        '{"type":"message_end","message":{"role":"assistant","content":[],'
        '"stopReason":"stop"}}\n'
    )
    parser.feed('{"type":"agent_end","messages":[]}\n')

    assert parser.finish() == initial_failure
    assert initial_failure is not None
    assert "stopReason is missing" in initial_failure


@_REQUIRES_POSIX_FIXTURE
def test_terminal_assistant_message_must_precede_agent_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = SUCCESS_LINES.splitlines(keepends=True)
    rc, _ = _run_fake(tmp_path, monkeypatch, lines[0] + lines[2] + lines[1])
    assert rc != 0


@_REQUIRES_POSIX_FIXTURE
def test_child_nonzero_is_failure_even_with_valid_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, _ = _run_fake(tmp_path, monkeypatch, SUCCESS_LINES, exit_code=7)
    assert rc == 7


@_REQUIRES_POSIX_FIXTURE
def test_runtime_launches_argv_without_a_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime()
    fake_pi, _ = _write_fake_pi(tmp_path)
    monkeypatch.setenv("PI_FIXTURE", SUCCESS_LINES)
    real_popen = runtime.subprocess.Popen
    calls: list[tuple[object, dict]] = []

    def _recording_popen(command, **kwargs):
        calls.append((command, kwargs))
        return real_popen(command, **kwargs)

    monkeypatch.setattr(runtime.subprocess, "Popen", _recording_popen)
    assert runtime.run_pi("prompt", pi_binary=str(fake_pi), timeout_seconds=2) == 0
    assert isinstance(calls[0][0], list)
    assert calls[0][1].get("shell", False) is False


@_REQUIRES_POSIX_FIXTURE
def test_runtime_restores_signal_handlers_after_normal_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime()
    fake_pi, _ = _write_fake_pi(tmp_path)
    monkeypatch.setenv("PI_FIXTURE", SUCCESS_LINES)
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    real_signal = signal.signal
    changes: list[tuple[int, object]] = []

    def _recording_signal(signum, handler):
        changes.append((signum, handler))
        return real_signal(signum, handler)

    monkeypatch.setattr(runtime.signal, "signal", _recording_signal)
    assert runtime.run_pi("prompt", pi_binary=str(fake_pi), timeout_seconds=2) == 0
    assert any(callable(handler) for _, handler in changes)
    assert signal.getsignal(signal.SIGTERM) is previous[signal.SIGTERM]
    assert signal.getsignal(signal.SIGINT) is previous[signal.SIGINT]


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "killpg"),
    reason="spawn-interleaving process-tree probe requires POSIX process groups",
)
def test_signal_between_child_spawn_and_assignment_cleans_process_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime()
    fake_pi, _ = _write_fake_pi(tmp_path)
    pi_pid_file = tmp_path / "pi.pid"
    descendant_pid_file = tmp_path / "descendant.pid"
    ready_file = tmp_path / "ready"
    monkeypatch.setenv("PI_SELF_PID", str(pi_pid_file))
    monkeypatch.setenv("PI_DESCENDANT_PID", str(descendant_pid_file))
    monkeypatch.setenv("PI_READY", str(ready_file))
    monkeypatch.setenv("PI_SLEEP", "60")
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    real_popen = runtime.subprocess.Popen
    spawned: list[subprocess.Popen] = []

    def _signal_before_assignment(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        spawned.append(child)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if ready_file.exists():
                break
            if child.poll() is not None:
                pytest.fail(f"fake Pi exited before readiness: rc={child.returncode}")
            time.sleep(0.05)
        else:
            pytest.fail("fake Pi did not publish spawn-race readiness")
        os.kill(os.getpid(), signal.SIGTERM)
        os.kill(os.getpid(), signal.SIGINT)
        return child

    monkeypatch.setattr(runtime.subprocess, "Popen", _signal_before_assignment)
    child_pids: list[int] = []
    try:
        rc = runtime.run_pi("prompt", pi_binary=str(fake_pi), timeout_seconds=10)
        child_pids = [
            int(pi_pid_file.read_text()),
            int(descendant_pid_file.read_text()),
        ]

        assert rc == 128 + signal.SIGTERM
        assert signal.getsignal(signal.SIGTERM) is previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) is previous[signal.SIGINT]
        for child_pid in child_pids:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail(f"Pi spawn-race process survived SIGTERM: {child_pid}")
    finally:
        for child in spawned:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
        for child_pid in child_pids:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


@_REQUIRES_POSIX_FIXTURE
def test_timeout_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rc, _ = _run_fake(tmp_path, monkeypatch, SUCCESS_LINES, sleep=1, timeout=0.05)
    assert rc == 124


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "killpg"),
    reason="process-group descendant probe requires POSIX process groups",
)
def test_timeout_terminates_descendant_process_and_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime()
    fake_pi, _ = _write_fake_pi(tmp_path)
    descendant_pid_file = tmp_path / "descendant.pid"
    monkeypatch.setenv("PI_DESCENDANT_PID", str(descendant_pid_file))
    monkeypatch.setenv("PI_SLEEP", "60")

    rc = runtime.run_pi("prompt", pi_binary=str(fake_pi), timeout_seconds=1)

    assert rc == 124
    descendant_pid = int(descendant_pid_file.read_text())
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            try:
                os.kill(descendant_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail(f"Pi descendant survived timeout: pid={descendant_pid}")
    finally:
        try:
            os.kill(descendant_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX process-group termination is covered through the process seam",
)
def test_process_group_escalation_precedes_reap_without_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()
    events: list[tuple[str, int | float]] = []

    class _Process:
        pid = 424242
        returncode = None

        def wait(self, timeout: float) -> int:
            events.append(("wait", timeout))
            self.returncode = -signal.SIGTERM
            return self.returncode

    monkeypatch.setattr(
        runtime,
        "signal_process_group",
        lambda _pid, sent_signal: events.append(("signal_process_group", sent_signal)),
    )
    monkeypatch.setattr(
        runtime.time,
        "sleep",
        lambda seconds: events.append(("sleep", seconds)),
    )

    runtime._terminate_process_tree(_Process())

    assert events == [
        ("signal_process_group", signal.SIGTERM),
        ("sleep", 1),
        ("signal_process_group", signal.SIGKILL),
        ("wait", 1),
    ]


def test_already_reaped_process_never_reuses_numeric_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime()

    class _ReapedProcess:
        pid = 424242
        returncode = 0

        def wait(self, timeout: float) -> int:
            pytest.fail("already-reaped process must not be waited again")

    monkeypatch.setattr(
        runtime,
        "signal_process_group",
        lambda *_args: pytest.fail("reaped PID/PGID must never be signaled"),
    )
    monkeypatch.setattr(
        runtime.time,
        "sleep",
        lambda _seconds: pytest.fail("already-reaped process needs no grace period"),
    )

    runtime._terminate_process_tree(_ReapedProcess())


@pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX process-group termination is covered through the process seam",
)
@pytest.mark.parametrize("denied_signal", _POSIX_TERMINATION_SIGNALS)
def test_process_group_signal_failures_are_contained_by_the_process_seam(
    monkeypatch: pytest.MonkeyPatch,
    denied_signal: int,
) -> None:
    runtime = _runtime()
    signals: list[int] = []

    class _Process:
        pid = 424242
        returncode = None
        terminate_calls = 0
        kill_calls = 0
        waits = 0

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1

        def wait(self, timeout: float) -> int:
            self.waits += 1
            self.returncode = -denied_signal
            return self.returncode

    def _signal_process_group(_pid: int, sent_signal: int) -> None:
        signals.append(sent_signal)
        if sent_signal == denied_signal:
            # The canonical seam contains platform signalling failures.
            return

    process = _Process()
    monkeypatch.setattr(runtime, "signal_process_group", _signal_process_group)
    monkeypatch.setattr(runtime.time, "sleep", lambda _seconds: None)

    runtime._terminate_process_tree(process)

    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert process.terminate_calls == 0
    assert process.kill_calls == 0


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "killpg"),
    reason="external launcher-group termination probe requires POSIX process groups",
)
def test_external_launcher_termination_cleans_detached_pi_tree(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_pi, _ = _write_fake_pi(fake_bin)
    pi_pid_file = tmp_path / "pi.pid"
    descendant_pid_file = tmp_path / "descendant.pid"
    ready_file = tmp_path / "ready"
    launcher = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "delegate-to-pi.sh"
    )
    env = {
        **os.environ,
        "PATH": f"{fake_pi.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        "SUPERHARNESS_PYTHON": sys.executable,
        "PI_SELF_PID": str(pi_pid_file),
        "PI_DESCENDANT_PID": str(descendant_pid_file),
        "PI_READY": str(ready_file),
        "PI_SLEEP": "60",
    }
    launcher_proc = subprocess.Popen(
        [
            str(launcher),
            "--project",
            str(project),
            "--prompt",
            "fixture external termination",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )

    child_pids: list[int] = []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if ready_file.exists():
                break
            if launcher_proc.poll() is not None:
                pytest.fail(
                    "launcher exited before fake Pi readiness: "
                    f"rc={launcher_proc.returncode} stderr={launcher_proc.stderr.read()}"
                )
            time.sleep(0.05)
        else:
            pytest.fail("fake Pi did not publish readiness")

        child_pids = [
            int(pi_pid_file.read_text()),
            int(descendant_pid_file.read_text()),
        ]
        os.killpg(launcher_proc.pid, signal.SIGTERM)
        launcher_proc.communicate(timeout=10)

        assert launcher_proc.returncode not in {None, 0}
        for child_pid in child_pids:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail(f"detached Pi process survived launcher SIGTERM: {child_pid}")
    finally:
        if launcher_proc.poll() is None:
            os.killpg(launcher_proc.pid, signal.SIGKILL)
            launcher_proc.wait(timeout=5)
        for child_pid in child_pids:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_missing_binary_returns_nonzero(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _runtime().run_pi(
        "prompt", pi_binary="definitely-missing-pi-binary", timeout_seconds=1
    )
    assert rc == 127
    assert "Pi executable not found" in capsys.readouterr().err


def test_usage_and_cost_are_retained_without_event_history() -> None:
    runtime = _runtime()
    parser = runtime.PiEventParser()
    parser.feed('{"type":"session","version":3,"id":"s"}\n')
    parser.feed(
        '{"type":"message_end","message":{"role":"assistant","content":[], '
        '"usage":{"input":12,"output":3},"cost":{"total":0.004},'
        '"stopReason":"stop"}}\n'
    )
    parser.feed('{"type":"agent_end","messages":[]}\n')

    assert parser.finish() is None
    assert parser.usage == {"input": 12, "output": 3}
    assert parser.cost == {"total": 0.004}
    assert not hasattr(parser, "events")


@_REQUIRES_POSIX_FIXTURE
def test_launcher_runs_runtime_with_fake_pi_and_project_cwd(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_pi, record = _write_fake_pi(fake_bin)
    assert fake_pi.parent == fake_bin
    launcher = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "delegate-to-pi.sh"
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "SUPERHARNESS_PYTHON": sys.executable,
        "PI_RECORD": str(record),
        "PI_FIXTURE": SUCCESS_LINES,
    }

    result = subprocess.run(
        [
            str(launcher),
            "--project",
            str(project),
            "--prompt",
            "launcher prompt\nsecond line",
            "--model",
            "provider-a/model-a",
            "--effort",
            "high",
        ],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == SUCCESS_LINES
    invocation = json.loads(record.read_text())
    assert invocation["cwd"] == str(project)
    assert invocation["argv"].count("launcher prompt\nsecond line") == 1


@pytest.mark.parametrize("args", [[], ["--project"], ["--prompt"], ["--bogus"]])
@_REQUIRES_POSIX_FIXTURE
def test_launcher_rejects_incomplete_or_unknown_arguments_without_invoking_pi(
    tmp_path: Path, args: list[str]
) -> None:
    fake_pi, record = _write_fake_pi(tmp_path)
    launcher = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "delegate-to-pi.sh"
    )
    result = subprocess.run(
        [str(launcher), *args],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{fake_pi.parent}{os.pathsep}{os.environ.get('PATH', '')}",
            "SUPERHARNESS_PYTHON": sys.executable,
            "PI_RECORD": str(record),
        },
        timeout=20,
    )
    assert result.returncode != 0
    assert not record.exists()


@_REQUIRES_POSIX_FIXTURE
def test_launcher_help_does_not_invoke_pi(tmp_path: Path) -> None:
    fake_pi, record = _write_fake_pi(tmp_path)
    launcher = (
        Path(__file__).parents[2]
        / "src"
        / "superharness"
        / "scripts"
        / "delegate-to-pi.sh"
    )
    result = subprocess.run(
        [str(launcher), "--help"],
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{fake_pi.parent}{os.pathsep}{os.environ.get('PATH', '')}",
            "SUPERHARNESS_PYTHON": sys.executable,
            "PI_RECORD": str(record),
        },
        timeout=20,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert not record.exists()


def _dispatch_context(project: Path, *, target: str = "pi", **overrides):
    runtime = _dispatch_runtime()
    values = {
        "project_dir": str(project),
        "inbox_file": str(project / ".superharness" / "inbox.yaml"),
        "contract_file": str(project / ".superharness" / "contract.yaml"),
        "print_only": False,
        "non_interactive": True,
        "codex_bypass": False,
        "launcher_timeout": 1,
        "script_dir": "scripts",
        "sqlite_primary": True,
        "item_to": target,
        "item_task": "fixture-task",
        "item_project": str(project),
    }
    values.update(overrides)
    return runtime.DispatchContext(**values)


def _init_git_repo(project: Path, *, commit: bool) -> None:
    project.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "ALLOW_MAIN_COMMIT": "1"}
    for command in (
        ["git", "init", str(project)],
        [
            "git",
            "-C",
            str(project),
            "config",
            "user.email",
            "fixture@example.invalid",
        ],
        ["git", "-C", str(project), "config", "user.name", "Fixture"],
        ["git", "-C", str(project), "config", "core.hooksPath", "/dev/null"],
    ):
        subprocess.run(command, check=True, capture_output=True, env=env)
    if commit:
        (project / "tracked.txt").write_text("fixture\n")
        subprocess.run(
            ["git", "-C", str(project), "add", "tracked.txt"],
            check=True,
            capture_output=True,
            env=env,
        )
        subprocess.run(
            ["git", "-C", str(project), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
            env=env,
        )


def test_noninteractive_pi_dispatch_always_uses_worktree(tmp_path: Path) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    _init_git_repo(project, commit=True)
    ctx = _dispatch_context(project)

    try:
        assert runtime._has_dirty_worktree(str(project)) is False
        assert runtime._resolve_execution_context(ctx) is None
        assert ctx.worktree_dir is not None
        assert ctx.exec_project == ctx.worktree_dir
        assert Path(ctx.worktree_dir).is_dir()
    finally:
        if ctx.worktree_dir:
            assert runtime._git_worktree_remove(str(project), ctx.worktree_dir)


def test_pi_worker_copy_branches_from_canonical_git_project(tmp_path: Path) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    _init_git_repo(project, commit=True)
    harness = project / ".superharness"
    harness.mkdir()
    worker = tmp_path / "worker"
    worker.mkdir()
    (worker / ".superharness").symlink_to(harness, target_is_directory=True)
    ctx = _dispatch_context(
        worker,
        project_dir=str(worker),
        item_project=str(project),
    )

    try:
        assert runtime._resolve_execution_context(ctx) is None
        assert ctx.worktree_dir is not None
        assert ctx.worktree_source_dir == str(project)
        assert ctx.exec_project == ctx.worktree_dir
    finally:
        if ctx.worktree_dir:
            assert runtime._git_worktree_remove(
                ctx.worktree_source_dir, ctx.worktree_dir
            )


def test_noninteractive_pi_dispatch_refuses_non_git_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "not-git"
    project.mkdir()
    ctx = _dispatch_context(project)

    assert _dispatch_runtime()._resolve_execution_context(ctx) == 1
    assert ctx.worktree_dir is None
    assert "Git repository" in capsys.readouterr().err


def test_noninteractive_pi_dispatch_refuses_unborn_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "unborn"
    _init_git_repo(project, commit=False)
    ctx = _dispatch_context(project)

    assert _dispatch_runtime()._resolve_execution_context(ctx) == 1
    assert ctx.worktree_dir is None
    assert "committed HEAD" in capsys.readouterr().err


def test_noninteractive_pi_dispatch_refuses_worktree_creation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    _init_git_repo(project, commit=True)
    ctx = _dispatch_context(project)
    monkeypatch.setattr(runtime, "_git_worktree_add", lambda *_: None)

    assert runtime._resolve_execution_context(ctx) == 1
    assert ctx.exec_project == str(project)
    assert "could not create" in capsys.readouterr().err


@pytest.mark.parametrize("failure_mode", ["preflight", "add"])
def test_claimed_pi_isolation_failure_becomes_terminal_without_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_mode: str
) -> None:
    runtime = _dispatch_runtime()
    from superharness.engine import inbox_dao
    from superharness.engine.db import get_connection, init_db

    project = tmp_path / "not-git"
    if failure_mode == "add":
        _init_git_repo(project, commit=True)
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    inbox_file = harness / "inbox.yaml"
    contract_file = harness / "contract.yaml"
    conn = get_connection(str(project))
    init_db(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("pi-task", "Pi task", "plan_approved", 1, "2026-01-01T00:00:00Z"),
    )
    inbox_dao.enqueue(
        conn,
        id="pi-item",
        task_id="pi-task",
        target_agent="pi",
        project_path=str(project),
        now="2026-01-01T00:00:00Z",
    )
    conn.commit()
    conn.close()
    lock = runtime._MkdirLock(str(inbox_file) + ".lock.d")
    assert lock.acquire()
    monkeypatch.setattr(
        runtime,
        "_execute_agent",
        lambda *_: pytest.fail("Pi process must not start after isolation failure"),
    )
    if failure_mode == "add":
        monkeypatch.setattr(runtime, "_git_worktree_add", lambda *_: None)

    rc = runtime._do_dispatch(
        inbox_file=str(inbox_file),
        contract_file=str(contract_file),
        project_dir=str(project),
        target_filter="pi",
        print_only=False,
        non_interactive=True,
        codex_bypass=False,
        launcher_timeout=1,
        script_dir="scripts",
        lock=lock,
        sqlite_primary=True,
    )

    assert rc == 1
    conn = get_connection(str(project))
    init_db(conn)
    row = inbox_dao.get(conn, "pi-item")
    conn.close()
    assert row is not None
    assert row.status in {"failed", "paused"}
    assert "isolated Git worktree" in (row.failed_reason or "")
    assert row.pid in {None, 0}


def test_clean_other_agent_dispatch_preserves_main_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    _init_git_repo(project, commit=True)
    ctx = _dispatch_context(project, target="codex-cli")
    called = False

    def _unexpected_add(*_args):
        nonlocal called
        called = True

    monkeypatch.setattr(runtime, "_git_worktree_add", _unexpected_add)
    assert runtime._resolve_execution_context(ctx) is None
    assert called is False
    assert ctx.exec_project == str(project)


def test_pi_print_only_preserves_existing_worktree_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    project.mkdir()
    ctx = _dispatch_context(project, print_only=True)
    monkeypatch.setattr(
        runtime,
        "_git_worktree_add",
        lambda *_: pytest.fail("worktree creation should have been skipped"),
    )
    assert runtime._resolve_execution_context(ctx) is None
    assert ctx.exec_project == str(project)


def test_other_agent_discussion_preserves_worktree_exemption(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    project.mkdir()
    ctx = _dispatch_context(
        project,
        target="codex-cli",
        item_task="discuss-fixture/round-1",
    )
    monkeypatch.setattr(
        runtime,
        "_git_worktree_add",
        lambda *_: pytest.fail("other-agent discussion must not create a worktree"),
    )
    assert runtime._resolve_execution_context(ctx) is None
    assert ctx.worktree_dir is None


def test_noninteractive_pi_discussion_dispatch_uses_worktree(tmp_path: Path) -> None:
    runtime = _dispatch_runtime()
    project = tmp_path / "repo"
    _init_git_repo(project, commit=True)
    ctx = _dispatch_context(project, item_task="discuss-fixture/round-1")

    try:
        assert runtime._resolve_execution_context(ctx) is None
        assert ctx.is_discussion is True
        assert ctx.worktree_dir is not None
        assert ctx.exec_project == ctx.worktree_dir
    finally:
        if ctx.worktree_dir:
            assert runtime._git_worktree_remove(str(project), ctx.worktree_dir)
