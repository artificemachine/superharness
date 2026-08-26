"""Safe one-shot runtime for Pi's JSONL print mode."""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, BinaryIO, TextIO

from superharness.engine.process import signal_process_group

_DEFAULT_TIMEOUT_SECONDS = 3600.0
_MAX_TERMINAL_TEXT_CHARS = 1_000_000
_MAX_CAPTURE_BYTES = 4_000_000
_MAX_JSONL_RECORD_BYTES = 2_000_000
_CAPTURE_CHUNK_BYTES = 64 * 1024
_EFFORT_TO_THINKING = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "max": "xhigh",
}
_TERMINAL_SUCCESS_STOP_REASONS = frozenset({"stop", "length"})
_KNOWN_STOP_REASONS = _TERMINAL_SUCCESS_STOP_REASONS | {
    "toolUse",
    "error",
    "aborted",
}


def build_command(
    prompt: str,
    *,
    model: str = "",
    effort: str = "",
    pi_binary: str = "pi",
    no_tools: bool = False,
) -> list[str]:
    """Build one ephemeral Pi JSON-print invocation without a shell."""
    command = [
        pi_binary,
        "--mode",
        "json",
        "--no-session",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
    ]
    if no_tools:
        command.append("--no-tools")
    if model:
        command.extend(("--model", model))
    if effort:
        try:
            thinking = _EFFORT_TO_THINKING[effort]
        except KeyError as exc:
            supported = ", ".join(_EFFORT_TO_THINKING)
            raise ValueError(
                f"unsupported Pi effort {effort!r}; expected: {supported}"
            ) from exc
        command.extend(("--thinking", thinking))
    command.extend(("-p", prompt))
    return command


@dataclass
class PiEventParser:
    """Bounded state machine for one Pi JSONL turn."""

    session_id: str = ""
    usage: dict = field(default_factory=dict)
    cost: dict = field(default_factory=dict)
    assistant_message_count: int = 0
    terminal_success_count: int = 0
    agent_end_seen: bool = False
    terminal_text: str = ""
    _failure: str = ""

    def _fail(self, message: str) -> None:
        if not self._failure:
            self._failure = message

    def feed(self, line: str) -> None:
        """Consume one already-forwarded JSONL line."""
        if self._failure:
            return
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            self._fail(f"malformed Pi JSONL: {exc}")
            return
        if not isinstance(event, dict):
            self._fail("malformed Pi JSONL: event must be an object")
            return

        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            self._fail("malformed Pi JSONL: event type is missing")
            return
        if self.agent_end_seen:
            self._fail(f"Pi protocol error: event {event_type!r} followed agent_end")
            return

        if event_type == "session":
            if self.assistant_message_count:
                self._fail("Pi protocol error: session event followed assistant message")
                return
            session_id = event.get("id")
            if isinstance(session_id, str):
                self.session_id = session_id
            return

        if event_type == "message_end":
            message = event.get("message")
            if not isinstance(message, dict):
                self._fail("Pi protocol error: message_end.message must be an object")
                return
            if message.get("role") != "assistant":
                return
            self.assistant_message_count += 1

            usage = message.get("usage")
            cost = message.get("cost")
            self.usage = dict(usage) if isinstance(usage, dict) else {}
            self.cost = dict(cost) if isinstance(cost, dict) else {}

            error_message = message.get("errorMessage")
            if error_message:
                self._fail(f"Pi assistant error: {error_message}")
                return

            stop_reason = message.get("stopReason")
            if not isinstance(stop_reason, str) or not stop_reason:
                self._fail("Pi protocol error: assistant stopReason is missing")
                return
            if stop_reason not in _KNOWN_STOP_REASONS:
                self._fail(
                    "Pi protocol error: unsupported assistant "
                    f"stopReason {stop_reason!r}"
                )
                return
            if stop_reason == "error":
                self._fail("Pi assistant error: assistant stopReason was error")
                return
            if stop_reason == "aborted":
                self._fail("Pi assistant error: assistant aborted")
                return
            if stop_reason == "toolUse":
                if self.terminal_success_count:
                    self._fail(
                        "Pi protocol error: assistant toolUse followed "
                        "terminal-success message"
                    )
                return

            if self.terminal_success_count:
                self._fail(
                    "Pi protocol error: duplicate terminal-success "
                    "assistant message_end"
                )
                return
            content = message.get("content")
            text_parts: list[str] = []
            text_length = 0
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "text":
                        continue
                    text = block.get("text")
                    if not isinstance(text, str):
                        continue
                    text_length += len(text)
                    if text_length > _MAX_TERMINAL_TEXT_CHARS:
                        self._fail("Pi protocol error: terminal text exceeds size limit")
                        return
                    text_parts.append(text)
            self.terminal_text = "".join(text_parts)
            self.terminal_success_count = 1
            return

        if event_type == "agent_end":
            self.agent_end_seen = True
            if self.terminal_success_count != 1:
                self._fail(
                    "Pi protocol error: agent_end arrived without an "
                    "assistant terminal-success message_end"
                )
            return

    def finish(self) -> str | None:
        """Return the failure reason, or ``None`` for one complete valid turn."""
        if self._failure:
            return self._failure
        if self.terminal_success_count != 1:
            return "Pi protocol error: missing assistant terminal-success message_end"
        if not self.agent_end_seen:
            return "Pi protocol error: truncated stream (missing agent_end)"
        return None


def extract_terminal_text(stdout: str) -> str:
    """Extract one bounded terminal assistant text from a valid Pi JSONL turn."""
    parser = PiEventParser()
    for line in stdout.splitlines():
        parser.feed(line)
    if parser.finish() is not None:
        raise ValueError("invalid Pi JSONL terminal stream")
    terminal_text = parser.terminal_text.strip()
    if not terminal_text:
        raise ValueError("Pi JSONL terminal stream contained no assistant text")
    return terminal_text


@dataclass(frozen=True)
class PiCaptureResult:
    """Sanitized subprocess result for bounded orchestrator capture."""

    returncode: int
    stdout: str
    stderr: str = ""


class PiCaptureError(RuntimeError):
    """A bounded Pi capture failed without retaining its raw output."""


def _process_group_options() -> dict[str, object]:
    if os.name == "posix":
        return {"start_new_session": True}
    if os.name == "nt" and hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {}


def _terminate_process_tree(proc: subprocess.Popen[Any]) -> None:
    """Terminate Pi's tree while its unreaped leader pins the process identity."""
    if proc.returncode is not None:
        return

    if os.name == "posix":
        # Pi is spawned in its own session. Keep the POSIX group signalling
        # mechanics behind the canonical process seam.
        signal_process_group(proc.pid, signal.SIGTERM)
    elif os.name == "nt" and hasattr(signal, "CTRL_BREAK_EVENT"):
        try:
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        except OSError:
            pass
    else:
        try:
            proc.terminate()
        except OSError:
            pass

    # Do not poll or wait here: reaping the group leader would allow its numeric
    # PID/PGID to be reused before escalation. A bounded grace sleep keeps the
    # original leader (running or zombie) as the stable identity anchor.
    time.sleep(1)

    if os.name == "posix":
        signal_process_group(proc.pid, signal.SIGKILL)
    elif os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        except OSError:
            pass
    else:
        try:
            proc.kill()
        except OSError:
            pass

    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _read_lines(
    stream: TextIO,
    output: queue.Queue[str | None],
    stop: threading.Event,
) -> None:
    def _put(value: str | None) -> bool:
        while not stop.is_set():
            try:
                output.put(value, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    try:
        for line in stream:
            if not _put(line):
                return
    except (OSError, ValueError):
        pass
    finally:
        _put(None)


def _close_reader(
    proc: subprocess.Popen[Any],
    reader: threading.Thread,
    stop: threading.Event,
) -> None:
    stop.set()
    if proc.stdout is not None:
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    reader.join(timeout=1)


def _read_chunks(
    stream: BinaryIO,
    output: queue.Queue[bytes | None],
    stop: threading.Event,
) -> None:
    def _put(value: bytes | None) -> bool:
        while not stop.is_set():
            try:
                output.put(value, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    try:
        while not stop.is_set():
            chunk = stream.read(_CAPTURE_CHUNK_BYTES)
            if not chunk:
                break
            if not _put(chunk):
                return
    except (OSError, ValueError):
        pass
    finally:
        _put(None)


def capture_pi_command(
    command: list[str],
    *,
    cwd: str,
    timeout_seconds: float,
) -> PiCaptureResult:
    """Capture Pi stdout incrementally with total and per-record byte bounds."""
    proc: subprocess.Popen[bytes] | None = None
    reader: threading.Thread | None = None
    stop_reader = threading.Event()
    cleanup_started = False
    pending_signal: int | None = None
    previous_handlers: dict[int, object] = {}

    def _cleanup() -> None:
        nonlocal cleanup_started
        if cleanup_started or proc is None:
            return
        cleanup_started = True
        _terminate_process_tree(proc)
        if reader is not None:
            _close_reader(proc, reader, stop_reader)
        elif proc.stdout is not None:
            try:
                proc.stdout.close()
            except (OSError, ValueError):
                pass

    def _raise_for_signal(signum: int) -> None:
        if signum == signal.SIGINT:
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    def _handle_termination(signum: int, _frame: object) -> None:
        nonlocal pending_signal
        if pending_signal is None:
            pending_signal = signum
        if proc is None or cleanup_started:
            return
        _cleanup()
        _raise_for_signal(pending_signal)

    def _abort(message: str) -> None:
        _cleanup()
        raise PiCaptureError(message)

    try:
        if threading.current_thread() is threading.main_thread():
            for handled_signal in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[handled_signal] = signal.getsignal(handled_signal)
                signal.signal(handled_signal, _handle_termination)

        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            **_process_group_options(),
        )
        if pending_signal is not None:
            _cleanup()
            _raise_for_signal(pending_signal)

        assert proc.stdout is not None
        chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
        reader = threading.Thread(
            target=_read_chunks,
            args=(proc.stdout, chunks, stop_reader),
            daemon=True,
        )
        reader.start()
        deadline = time.monotonic() + timeout_seconds
        captured = bytearray()
        record_bytes = 0

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _abort("Pi orchestrator capture timed out")
            try:
                chunk = chunks.get(timeout=remaining)
            except queue.Empty:
                _abort("Pi orchestrator capture timed out")
            if chunk is None:
                break
            if len(captured) + len(chunk) > _MAX_CAPTURE_BYTES:
                _abort("Pi orchestrator stdout exceeded total capture limit")

            offset = 0
            while offset < len(chunk):
                newline = chunk.find(b"\n", offset)
                if newline < 0:
                    record_bytes += len(chunk) - offset
                    if record_bytes > _MAX_JSONL_RECORD_BYTES:
                        _abort("Pi orchestrator JSONL record exceeded capture limit")
                    break
                record_bytes += newline - offset
                if record_bytes > _MAX_JSONL_RECORD_BYTES:
                    _abort("Pi orchestrator JSONL record exceeded capture limit")
                record_bytes = 0
                offset = newline + 1
            captured.extend(chunk)

        _close_reader(proc, reader, stop_reader)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _abort("Pi orchestrator capture timed out")
        try:
            returncode = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            _abort("Pi orchestrator capture timed out")
        return PiCaptureResult(
            returncode=returncode,
            stdout=captured.decode("utf-8", errors="replace"),
        )
    except BaseException:
        _cleanup()
        raise
    finally:
        for handled_signal, previous_handler in previous_handlers.items():
            signal.signal(handled_signal, previous_handler)


class _ExternalTermination(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"received signal {signum}")


def run_pi(
    prompt: str,
    *,
    model: str = "",
    effort: str = "",
    pi_binary: str = "pi",
    cwd: str | None = None,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> int:
    """Run Pi, tee every JSONL line once, and fail closed on protocol errors."""
    command = build_command(
        prompt,
        model=model,
        effort=effort,
        pi_binary=pi_binary,
    )
    proc: subprocess.Popen[str] | None = None
    reader: threading.Thread | None = None
    stop_reader = threading.Event()
    previous_handlers: dict[int, object] = {}
    pending_signal: int | None = None
    signal_cleanup_started = False

    def _cleanup_after_signal() -> None:
        nonlocal signal_cleanup_started
        if signal_cleanup_started or proc is None:
            return
        signal_cleanup_started = True
        _terminate_process_tree(proc)
        if reader is not None:
            _close_reader(proc, reader, stop_reader)
        elif proc.stdout is not None:
            try:
                proc.stdout.close()
            except OSError:
                pass

    def _handle_termination(signum: int, _frame: object) -> None:
        nonlocal pending_signal
        if pending_signal is None:
            pending_signal = signum
        if proc is None:
            return
        if signal_cleanup_started:
            return
        _cleanup_after_signal()
        raise _ExternalTermination(pending_signal)

    try:
        if threading.current_thread() is threading.main_thread():
            for handled_signal in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[handled_signal] = signal.getsignal(handled_signal)
                signal.signal(handled_signal, _handle_termination)

        try:
            proc = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **_process_group_options(),
            )
            if pending_signal is not None:
                _cleanup_after_signal()
                raise _ExternalTermination(pending_signal)
        except FileNotFoundError:
            print(f"Pi executable not found: {pi_binary}", file=sys.stderr)
            return 127
        except OSError as exc:
            print(f"Unable to execute Pi: {exc}", file=sys.stderr)
            return 126

        assert proc.stdout is not None
        lines: queue.Queue[str | None] = queue.Queue(maxsize=1)
        reader = threading.Thread(
            target=_read_lines,
            args=(proc.stdout, lines, stop_reader),
            daemon=True,
        )
        reader.start()
        parser = PiEventParser()
        deadline = time.monotonic() + timeout_seconds

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_process_tree(proc)
                _close_reader(proc, reader, stop_reader)
                print(f"Pi turn timed out after {timeout_seconds:g}s", file=sys.stderr)
                return 124
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty:
                _terminate_process_tree(proc)
                _close_reader(proc, reader, stop_reader)
                print(f"Pi turn timed out after {timeout_seconds:g}s", file=sys.stderr)
                return 124
            if line is None:
                break
            sys.stdout.write(line)
            sys.stdout.flush()
            parser.feed(line)

        _close_reader(proc, reader, stop_reader)
        remaining = deadline - time.monotonic()
        try:
            child_rc = proc.wait(timeout=max(remaining, 0))
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            print(f"Pi turn timed out after {timeout_seconds:g}s", file=sys.stderr)
            return 124

        protocol_error = parser.finish()
        if protocol_error:
            print(protocol_error, file=sys.stderr)
            return child_rc if child_rc else 1
        if child_rc:
            print(f"Pi exited with status {child_rc}", file=sys.stderr)
            return child_rc
        return 0
    except _ExternalTermination as exc:
        print(f"Pi runtime terminated by signal {exc.signum}", file=sys.stderr)
        return 128 + exc.signum
    finally:
        for handled_signal, previous_handler in previous_handlers.items():
            signal.signal(handled_signal, previous_handler)


def _timeout_from_environment() -> float:
    raw = os.environ.get("SUPERHARNESS_PI_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_TIMEOUT_SECONDS
    try:
        timeout = float(raw)
    except ValueError as exc:
        raise ValueError(
            "SUPERHARNESS_PI_TIMEOUT_SECONDS must be a positive number"
        ) from exc
    if timeout <= 0:
        raise ValueError("SUPERHARNESS_PI_TIMEOUT_SECONDS must be a positive number")
    return timeout


def _build_parser() -> argparse.ArgumentParser:
    class _CapUsage(argparse.HelpFormatter):
        def _format_usage(self, usage, actions, groups, prefix):
            return super()._format_usage(usage, actions, groups, "Usage: ")

    parser = argparse.ArgumentParser(
        prog="delegate-to-pi.sh",
        description="Run one ephemeral structured Pi worker turn.",
        formatter_class=_CapUsage,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--effort", choices=tuple(_EFFORT_TO_THINKING), default="")
    parser.add_argument("--task", default="")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yolo", action="store_true")
    parser.add_argument("--codex-bypass", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.prompt:
        print("--prompt must not be empty", file=sys.stderr)
        return 2
    if not os.path.isdir(args.project):
        print(f"Pi project directory does not exist: {args.project}", file=sys.stderr)
        return 2
    try:
        timeout = _timeout_from_environment()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return run_pi(
        args.prompt,
        model=args.model,
        effort=args.effort,
        cwd=args.project,
        timeout_seconds=timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
