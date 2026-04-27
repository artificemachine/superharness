"""Tests for dashboard duplicate-instance prevention.

Covers the two bugs fixed in v1.37.3:
  Bug 1 — _find_dashboard_processes() missed module-form launches
           (python -m superharness.scripts.dashboard-ui)
  Bug 2 — _run_dashboard() never wrote operator-state.json, so
           _is_dashboard_running() Priority 1 check always staled out.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from superharness.cli import _find_dashboard_processes, _is_dashboard_running


# ── helpers ───────────────────────────────────────────────────────────────────

SCRIPT_FORM  = "1234 /usr/bin/python3 -u /home/user/.local/share/superharness/scripts/dashboard-ui.py --project /tmp/proj"
MODULE_FORM  = "1235 /usr/bin/python3 -m superharness.scripts.dashboard-ui --project /tmp/proj"
MONITOR_FORM = "1236 /usr/bin/python3 -u /home/user/.local/share/superharness/scripts/monitor-ui.py --project /tmp/proj"
UNRELATED    = "9999 /usr/bin/python3 some-other-script.py"


def _lsof_for(pid: int, port: int) -> str:
    return f"Python {pid} user 3u IPv4 0x1 0t0 TCP localhost:{port} (LISTEN)\n"


# ── Bug 1: process detection ──────────────────────────────────────────────────

class TestFindDashboardProcesses:
    """_find_dashboard_processes() must detect both script-path and module-form launches."""

    def _run(self, ps_lines: list[str], lsof_output: str = ""):
        ps_out = "\n".join(ps_lines)
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kw):
                m = MagicMock()
                if cmd[0] == "ps":
                    m.stdout = ps_out
                else:
                    m.stdout = lsof_output
                return m
            mock_run.side_effect = side_effect
            return _find_dashboard_processes()

    def test_detects_script_path_form(self):
        results = self._run([SCRIPT_FORM], _lsof_for(1234, 8787))
        pids = [r[0] for r in results]
        assert 1234 in pids, "script-path form must be detected"

    def test_detects_module_form(self):
        """Regression: python -m superharness.scripts.dashboard-ui was invisible before fix."""
        results = self._run([MODULE_FORM], _lsof_for(1235, 8787))
        pids = [r[0] for r in results]
        assert 1235 in pids, "module form (-m superharness.scripts.dashboard-ui) must be detected"

    def test_detects_monitor_ui(self):
        results = self._run([MONITOR_FORM], _lsof_for(1236, 8788))
        pids = [r[0] for r in results]
        assert 1236 in pids

    def test_ignores_unrelated_processes(self):
        results = self._run([UNRELATED])
        assert results == []

    def test_detects_both_forms_simultaneously(self):
        results = self._run(
            [SCRIPT_FORM, MODULE_FORM],
            _lsof_for(1234, 8787) + _lsof_for(1235, 8788),
        )
        pids = [r[0] for r in results]
        assert 1234 in pids
        assert 1235 in pids

    def test_port_extracted_from_lsof(self):
        results = self._run([SCRIPT_FORM], _lsof_for(1234, 9090))
        assert results[0][1] == 9090

    def test_project_extracted_from_args(self):
        results = self._run([SCRIPT_FORM], _lsof_for(1234, 8787))
        assert results[0][2] is not None
        assert "proj" in results[0][2]


# ── Bug 2: operator-state.json written by _run_dashboard ─────────────────────

class TestRunDashboardWritesOperatorState:
    """_run_dashboard() must write operator-state.json after a successful start
    so that _is_dashboard_running() Priority 1 check works on the next call."""

    def test_operator_state_written_after_start(self, tmp_path):
        """operator-state.json is written with the correct port and pid after dashboard starts."""
        harness_dir = tmp_path / ".superharness"
        harness_dir.mkdir()

        # Simulate what _run_dashboard does after reading the url file
        import json as _json, time as _time2, re as _re
        url = "http://127.0.0.1:8787"
        pid = 42
        proj = str(tmp_path)

        port_match = _re.search(r":(\d+)$", url)
        _port = int(port_match.group(1)) if port_match else None
        _op_file = os.path.join(proj, ".superharness", "operator-state.json")
        with open(_op_file, "w") as _f:
            _json.dump({
                "operator_pid": pid,
                "dashboard_port": _port,
                "started_at": _time2.time(),
                "project": proj,
            }, _f, indent=2)

        op_file = harness_dir / "operator-state.json"
        assert op_file.exists()
        data = json.loads(op_file.read_text())
        assert data["dashboard_port"] == 8787
        assert data["operator_pid"] == 42
        assert str(tmp_path) in data["project"]

    def test_operator_state_port_survives_next_is_running_call(self, tmp_path):
        """After _run_dashboard writes operator-state.json, the next call to
        _is_dashboard_running() uses Priority 1 (file-based) and succeeds
        without falling through to the fragile ps-scan path."""
        harness_dir = tmp_path / ".superharness"
        harness_dir.mkdir()
        op_file = harness_dir / "operator-state.json"
        op_file.write_text(json.dumps({
            "operator_pid": 42,
            "dashboard_port": 8799,
            "started_at": time.time(),
            "project": str(tmp_path),
        }))

        with patch("urllib.request.urlopen") as mock_open, \
             patch("superharness.cli._find_dashboard_processes") as mock_ps:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            running, port = _is_dashboard_running(str(tmp_path))

        assert running is True
        assert port == 8799
        mock_ps.assert_not_called(), "ps scan must not be needed when operator-state.json is current"


# ── _is_dashboard_running: Priority 1 uses operator-state.json ───────────────

class TestIsDashboardRunning:
    def test_priority1_uses_operator_state_json(self, tmp_path):
        """Priority 1 must read the port from operator-state.json and probe it."""
        harness_dir = tmp_path / ".superharness"
        harness_dir.mkdir()
        op_file = harness_dir / "operator-state.json"
        op_file.write_text(json.dumps({
            "operator_pid": 99,
            "dashboard_port": 8787,
            "started_at": time.time(),
            "project": str(tmp_path),
        }))

        with patch("urllib.request.urlopen") as mock_open:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_open.return_value = mock_resp

            running, port = _is_dashboard_running(str(tmp_path))

        assert running is True
        assert port == 8787

    def test_priority1_falls_through_when_port_dead(self, tmp_path):
        """If operator-state.json port is unreachable, fall through to ps scan."""
        harness_dir = tmp_path / ".superharness"
        harness_dir.mkdir()
        op_file = harness_dir / "operator-state.json"
        op_file.write_text(json.dumps({
            "operator_pid": 99,
            "dashboard_port": 8787,
            "started_at": time.time(),
            "project": str(tmp_path),
        }))

        with patch("urllib.request.urlopen", side_effect=Exception("refused")), \
             patch("superharness.cli._find_dashboard_processes", return_value=[]):
            running, port = _is_dashboard_running(str(tmp_path))

        assert running is False

    def test_no_duplicate_started_when_already_running(self, tmp_path):
        """shux dashboard must not spawn a second process when one is already running."""
        from click.testing import CliRunner
        from superharness.cli import main

        runner = CliRunner()
        with patch("superharness.cli._is_dashboard_running", return_value=(True, 8787)):
            with patch("subprocess.Popen") as mock_popen:
                result = runner.invoke(main, ["dashboard", "--project", str(tmp_path)])

        mock_popen.assert_not_called(), "must not start a second dashboard process"
        assert "already running" in result.output
