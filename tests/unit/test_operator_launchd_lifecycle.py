"""Regression tests for persistent operator launchd ownership."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / ".superharness").mkdir(parents=True)
    return project


def test_operator_stop_disables_and_boots_out_installed_service(tmp_path):
    """Persistent stop must win over KeepAlive and the healer."""
    from superharness.cli import main
    from superharness.engine import launchd_health

    project = _project(tmp_path)
    state_file = project / ".superharness" / "operator-state.json"
    state_file.write_text(
        json.dumps({"operator_pid": 91, "dashboard_pid": 92, "dashboard_port": 8787})
    )
    label = launchd_health.operator_label_for_project(project)
    plist = tmp_path / f"{label}.plist"
    plist.touch()
    calls: list[tuple[str, str]] = []

    with (
        patch.object(launchd_health, "plist_path_for_label", return_value=plist),
        patch.object(
            launchd_health,
            "disable",
            side_effect=lambda value: calls.append(("disable", value)) or True,
        ),
        patch.object(
            launchd_health,
            "bootout",
            side_effect=lambda value: calls.append(("bootout", value)) or True,
        ),
        patch("superharness.cli.os.kill") as kill,
    ):
        result = CliRunner().invoke(main, ["operator", "stop", "--project", str(project)])

    assert result.exit_code == 0, result.output
    assert calls == [("disable", label), ("bootout", label)]
    kill.assert_not_called()
    assert json.loads(state_file.read_text())["dashboard_pid"] == 92


def test_operator_stop_refuses_unverified_fallback_pid(tmp_path):
    """A stale state PID must not be signalled without command verification."""
    from superharness.cli import main
    from superharness.engine import launchd_health

    project = _project(tmp_path)
    (project / ".superharness" / "operator-state.json").write_text(
        json.dumps({"operator_pid": 91, "dashboard_pid": 92})
    )

    with (
        patch.object(
            launchd_health,
            "plist_path_for_label",
            return_value=tmp_path / "missing.plist",
        ),
        patch("superharness.cli.subprocess.run") as run,
        patch("superharness.cli.os.kill") as kill,
    ):
        run.return_value.stdout = "python dashboard-ui.py --project elsewhere"
        result = CliRunner().invoke(main, ["operator", "stop", "--project", str(project)])

    assert result.exit_code == 0, result.output
    assert "unverified" in result.output.lower()
    kill.assert_not_called()


def test_operator_stop_disables_legacy_label_for_the_same_project(tmp_path):
    """Stop must handle an installed service from a prior label scheme."""
    from superharness.cli import main
    from superharness.engine import launchd_health

    project = _project(tmp_path)
    calls: list[tuple[str, str]] = []
    legacy_label = "com.superharness.operator.legacy"
    with (
        patch.object(
            launchd_health,
            "operator_labels_for_project",
            return_value=[legacy_label],
        ),
        patch.object(
            launchd_health,
            "disable",
            side_effect=lambda value: calls.append(("disable", value)) or True,
        ),
        patch.object(
            launchd_health,
            "bootout",
            side_effect=lambda value: calls.append(("bootout", value)) or True,
        ),
        patch("superharness.cli.os.kill") as kill,
    ):
        result = CliRunner().invoke(main, ["operator", "stop", "--project", str(project)])

    assert result.exit_code == 0, result.output
    assert calls == [("disable", legacy_label), ("bootout", legacy_label)]
    kill.assert_not_called()


def test_explicit_operator_start_enables_and_bootstraps_installed_service(tmp_path):
    """An explicit user start reverses disabled launchd state before spawning."""
    from superharness.cli import _resume_installed_operator
    from superharness.engine import launchd_health

    project = _project(tmp_path)
    label = launchd_health.operator_label_for_project(project)
    plist = tmp_path / f"{label}.plist"
    plist.touch()

    with (
        patch.object(launchd_health, "plist_path_for_label", return_value=plist),
        patch.object(launchd_health, "enable", return_value=True) as enable,
        patch.object(launchd_health, "bootstrap", return_value=True) as bootstrap,
    ):
        assert _resume_installed_operator(project, no_daemon=False) is True

    enable.assert_called_once_with(label)
    bootstrap.assert_called_once_with(plist)


def test_launchd_no_daemon_entrypoint_does_not_bootstrap_recursively(tmp_path):
    """The launchd child itself must run the monitor, not bootstrap again."""
    from superharness.cli import _resume_installed_operator

    assert _resume_installed_operator(_project(tmp_path), no_daemon=True) is False


def test_operator_start_rejects_options_not_represented_in_installed_service(tmp_path):
    """Installed launchd arguments must not silently discard start options."""
    from superharness.cli import main
    from superharness.engine import launchd_health

    project = _project(tmp_path)
    plist = tmp_path / "operator.plist"
    plist.touch()
    with (
        patch.object(
            launchd_health,
            "operator_label_for_project",
            return_value="com.superharness.operator.test",
        ),
        patch.object(launchd_health, "plist_path_for_label", return_value=plist),
        patch.object(launchd_health, "enable", return_value=True),
        patch.object(launchd_health, "bootstrap", return_value=True),
    ):
        result = CliRunner().invoke(
            main,
            ["operator", "start", "--project", str(project), "--dashboard"],
        )

    assert result.exit_code == 2
    assert "cannot apply --dashboard" in result.output
    assert "operator install --dashboard" in result.output


def test_operator_install_passes_invoking_interpreter_to_installer(tmp_path):
    """The service must use the interpreter that owns the invoking package."""
    from superharness.cli import main
    from superharness.engine import launchd_health

    project = _project(tmp_path)
    with (
        patch.object(launchd_health, "heal"),
        patch.object(
            launchd_health,
            "operator_label_for_project",
            return_value="com.superharness.operator.test",
        ),
        patch.object(
            launchd_health,
            "plist_path_for_label",
            return_value=tmp_path / "operator.plist",
        ),
        patch("superharness.cli.subprocess.run") as run,
    ):
        result = CliRunner().invoke(
            main,
            ["operator", "install", "--project", str(project), "--no-watchdog"],
        )

    assert result.exit_code == 0, result.output
    assert run.call_args.kwargs["env"]["SUPERHARNESS_OPERATOR_PYTHON_BIN"] == sys.executable


def test_heal_skips_operator_disabled_by_user(tmp_path, monkeypatch):
    """Watchdog healing cannot resurrect a service explicitly disabled by stop."""
    from superharness.engine import launchd_health

    monkeypatch.setattr(launchd_health, "_is_macos", lambda: True)
    plist = tmp_path / "com.superharness.operator.abc.plist"
    plist.touch()

    with (
        patch.object(launchd_health, "is_disabled", return_value=True),
        patch.object(launchd_health, "bootstrap") as bootstrap,
    ):
        report = launchd_health.heal(operator_plist=plist)

    assert report.skipped_reason == "operator disabled by user"
    bootstrap.assert_not_called()
