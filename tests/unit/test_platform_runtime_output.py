"""Output forwarding coverage for the cross-platform agent launcher."""

from __future__ import annotations

import sys
from pathlib import Path

from superharness.engine.platform_runtime import launch_agent


def _write_child(tmp_path: Path, source: str) -> Path:
    child = tmp_path / "child.py"
    child.write_text(source, encoding="utf-8")
    return child


def test_launch_agent_forwards_stdout_on_success(tmp_path: Path, capsys) -> None:
    """Successful child stdout remains visible exactly once."""
    child = _write_child(tmp_path, "print('fixture stdout')\n")

    assert launch_agent([sys.executable, str(child)], cwd=str(tmp_path)) == 0

    captured = capsys.readouterr()
    assert captured.out == "fixture stdout\n"
    assert captured.err == ""


def test_launch_agent_keeps_empty_streams_empty(tmp_path: Path, capsys) -> None:
    """A silent child does not create parent output."""
    child = _write_child(tmp_path, "")

    assert launch_agent([sys.executable, str(child)], cwd=str(tmp_path)) == 0

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_launch_agent_forwards_stderr_and_returns_failure(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    """Failure stderr is forwarded while preserving audit and return semantics."""
    child = _write_child(
        tmp_path,
        "import sys\nprint('fixture stderr', file=sys.stderr)\nraise SystemExit(23)\n",
    )
    audit_messages: list[tuple[object, ...]] = []

    class Audit:
        def warning(self, *args: object) -> None:
            audit_messages.append(args)

    monkeypatch.setattr(
        "superharness.logging_utils.get_audit_logger", lambda: Audit()
    )

    assert launch_agent([sys.executable, str(child)], cwd=str(tmp_path)) == 23

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "fixture stderr\n"
    assert audit_messages


def test_launch_agent_replaces_invalid_output_bytes(tmp_path: Path, capsys) -> None:
    """Invalid UTF-8 remains diagnosable through the existing replacement policy."""
    child = _write_child(
        tmp_path,
        "import sys\nsys.stdout.buffer.write(b'bad: \\xff\\n')\n",
    )

    assert launch_agent([sys.executable, str(child)], cwd=str(tmp_path)) == 0

    assert capsys.readouterr().out == "bad: \ufffd\n"
