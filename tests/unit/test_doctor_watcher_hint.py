"""The doctor watcher WARN must name a command that can clear it.

The check on macOS looks for the Guardian launchd job (or a live operator
process). `shux watcher-worker` installs a different job, so recommending it
leaves the warning in place.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def doctor_without_guardian(tmp_path, monkeypatch):
    """macOS, no Guardian launchd job, no live operator process."""
    (tmp_path / ".superharness").mkdir()
    monkeypatch.setattr("superharness.commands.doctor.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "superharness.commands.doctor._operator_launchd_status",
        lambda project_dir: ("com.superharness.operator.test1234", False),
    )
    monkeypatch.setattr(
        "superharness.commands.doctor._operator_running_for_project",
        lambda project_dir: False,
    )
    return tmp_path


def _watcher_lines(capsys, project) -> str:
    from superharness.commands import doctor

    try:
        doctor.main(["--project", str(project)])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("WARN watcher:"))
    return "\n".join(lines[start : start + 3])


def test_hint_points_at_the_command_that_clears_the_warning(
    doctor_without_guardian, capsys
):
    block = _watcher_lines(capsys, doctor_without_guardian)
    assert "shux operator install" in block
    assert "watcher-worker" not in block


def test_foreground_alternative_is_kept(doctor_without_guardian, capsys):
    block = _watcher_lines(capsys, doctor_without_guardian)
    assert "superharness watch --foreground --project ." in block
