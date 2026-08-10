"""Status surfaces must report the operator's actual launchd label."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _result(returncode: int, stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


def test_status_queries_the_operator_label_for_the_project(tmp_path):
    from superharness.commands import status
    from superharness.engine.launchd_health import operator_label_for_project

    project = tmp_path / "worker project"
    project.mkdir()
    label = operator_label_for_project(project)
    with patch.object(status, "subprocess") as subprocess:
        subprocess.run.return_value = _result(
            0, "state = running\nlast exit code = 0\n"
        )
        level, _detail = status._watcher_status_darwin(str(project))

    assert level == "ok"
    assert subprocess.run.call_args.args[0][-1].endswith(label)


def test_doctor_queries_the_operator_label_for_the_project(tmp_path):
    from superharness.commands import doctor
    from superharness.engine.launchd_health import operator_label_for_project

    project = tmp_path / "worker project"
    project.mkdir()
    with patch.object(doctor, "subprocess") as subprocess:
        subprocess.run.return_value = _result(0, "state = running")
        label, loaded = doctor._operator_launchd_status(str(project))

    assert label == operator_label_for_project(project)
    assert loaded is True
    assert subprocess.run.call_args.args[0][-1].endswith(label)
