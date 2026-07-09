"""doctor's watcher check only looks for the dedicated inbox-watcher launchd
label (com.superharness.inbox.<slug>). A project can also get watcher
functionality from a live `superharness operator` process (engine/operator.py
spawns its own internal watcher loop), registered under a different launchd
label (com.superharness.operator.<hash>) or run ad hoc in the foreground.
doctor should not warn "watcher not loaded" when such a process is live.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock


def _ps_aux_result(lines: list[str]) -> MagicMock:
    r = MagicMock()
    r.stdout = "\n".join(lines)
    return r


class TestOperatorRunningForProject:
    def test_detects_live_operator_process_for_this_project(self):
        from superharness.commands.doctor import _operator_running_for_project

        project_dir = "/Users/x/DevOpsSec/superharness"
        ps_output = [
            "root  1  0.0  0.0  0 0 ?? S 0:00 /sbin/launchd",
            f"user  58745  0.0  0.1 0 0 ?? S 0:11 python -m superharness.cli operator start --no-daemon --project {project_dir}",
        ]
        with patch("subprocess.run", return_value=_ps_aux_result(ps_output)):
            assert _operator_running_for_project(project_dir) is True

    def test_no_match_when_no_operator_process(self):
        from superharness.commands.doctor import _operator_running_for_project

        project_dir = "/Users/x/DevOpsSec/superharness"
        ps_output = [
            "root  1  0.0  0.0  0 0 ?? S 0:00 /sbin/launchd",
            "user  222  0.0  0.1 0 0 ?? S 0:11 /usr/bin/python3 -m http.server",
        ]
        with patch("subprocess.run", return_value=_ps_aux_result(ps_output)):
            assert _operator_running_for_project(project_dir) is False

    def test_no_match_when_operator_runs_for_different_project(self):
        from superharness.commands.doctor import _operator_running_for_project

        project_dir = "/Users/x/DevOpsSec/superharness"
        other_project = "/Users/x/DevOpsSec/other-repo"
        ps_output = [
            f"user  1  0.0  0.1 0 0 ?? S 0:11 python -m superharness.cli operator start --no-daemon --project {other_project}",
        ]
        with patch("subprocess.run", return_value=_ps_aux_result(ps_output)):
            assert _operator_running_for_project(project_dir) is False

    def test_subprocess_failure_returns_false_not_raise(self):
        from superharness.commands.doctor import _operator_running_for_project

        with patch("subprocess.run", side_effect=OSError("ps not found")):
            assert _operator_running_for_project("/Users/x/proj") is False
