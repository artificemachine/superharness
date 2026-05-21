"""Unit tests for shux dashboard-kill and dashboard-list commands (v1.3.1).

Verifies all 6 acceptance criteria:
  AC1: dashboard-list shows PID, PORT, PROJECT, URL columns
  AC2: dashboard-list output includes hints for dashboard-kill and dashboard-kill --project
  AC3: dashboard-kill kills all dashboard processes and prints count
  AC4: dashboard-kill --port <N> kills only the process on that port
  AC5: dashboard-kill output hints user to run shux dashboard-list
  AC6: dashboard-list when nothing running prints "No dashboard processes running"
"""

import os
import signal
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from superharness.cli import main


# ─── helpers ─────────────────────────────────────────────────────────────────

def _proc(pid=1234, port=8787, proj="/tmp/myproject"):
    return (pid, port, proj)


# ─── AC1: dashboard-list shows PID, PORT, PROJECT, URL columns ─────────────────

class TestDashboardListColumns:
    def test_header_has_pid_port_project_url(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[_proc()]):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "PID" in result.output
        assert "PORT" in result.output
        assert "PROJECT" in result.output
        assert "URL" in result.output

    def test_row_shows_pid_port_basename_url(self):
        runner = CliRunner()
        proc = _proc(pid=5678, port=9000, proj="/tmp/myproject")
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[proc]):
            result = runner.invoke(main, ["dashboard-list"])
        assert "5678" in result.output
        assert "9000" in result.output
        assert "myproject" in result.output
        assert "http://127.0.0.1:9000" in result.output

    def test_unknown_port_shows_question_mark(self):
        runner = CliRunner()
        proc = _proc(pid=111, port=None, proj="/tmp/x")
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[proc]):
            result = runner.invoke(main, ["dashboard-list"])
        assert "?" in result.output
        assert "(port unknown)" in result.output

    def test_unknown_project_shows_question_mark(self):
        runner = CliRunner()
        proc = _proc(pid=222, port=8787, proj=None)
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[proc]):
            result = runner.invoke(main, ["dashboard-list"])
        assert "?" in result.output


# ─── AC2: dashboard-list hints for dashboard-kill and dashboard-kill --project ──────

class TestDashboardListHints:
    def test_kill_all_hint_always_shown(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[_proc()]):
            result = runner.invoke(main, ["dashboard-list"])
        assert "shux dashboard-kill" in result.output

    def test_kill_by_port_hint_shown_when_single_process(self):
        runner = CliRunner()
        proc = _proc(pid=1234, port=8787, proj="/tmp/proj")
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[proc]):
            result = runner.invoke(main, ["dashboard-list"])
        assert "dashboard-kill --port 8787" in result.output

    def test_kill_by_project_hint_shown_when_single_process(self):
        runner = CliRunner()
        proc = _proc(pid=1234, port=8787, proj="/tmp/proj")
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[proc]):
            result = runner.invoke(main, ["dashboard-list"])
        assert "dashboard-kill --project" in result.output
        assert "/tmp/proj" in result.output

    def test_port_and_project_hints_not_shown_for_multiple_processes(self):
        runner = CliRunner()
        procs = [_proc(1111, 8787, "/tmp/a"), _proc(2222, 8788, "/tmp/b")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-list"])
        # "kill all" hint is shown but NOT the specific --port or --project hint
        assert "shux dashboard-kill" in result.output
        assert "dashboard-kill --port" not in result.output
        assert "dashboard-kill --project" not in result.output


# ─── AC3: dashboard-kill kills all processes and prints count ──────────────────

class TestDashboardKillAll:
    def test_kills_all_processes_and_prints_count(self):
        runner = CliRunner()
        procs = [_proc(1111, 8787, "/tmp/a"), _proc(2222, 8788, "/tmp/b")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs), \
             patch("os.kill") as mock_kill:
            result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert mock_kill.call_count == 2
        assert "2 dashboard process(es) stopped" in result.output

    def test_no_processes_prints_not_found(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "No dashboard processes found" in result.output

    def test_single_process_killed_count_is_one(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[_proc()]), \
             patch("os.kill"):
            result = runner.invoke(main, ["dashboard-kill"])
        assert "1 dashboard process(es) stopped" in result.output


# ─── AC4: dashboard-kill --port <N> kills only the process on that port ─────────

class TestDashboardKillByPort:
    def test_kills_only_matching_port(self):
        runner = CliRunner()
        procs = [_proc(1111, 8787, "/tmp/a"), _proc(2222, 8788, "/tmp/b")]
        killed_pids = []

        def fake_kill(pid, sig):
            killed_pids.append(pid)

        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs), \
             patch("os.kill", side_effect=fake_kill):
            result = runner.invoke(main, ["dashboard-kill", "--port", "8787"])
        assert result.exit_code == 0
        assert killed_pids == [1111]
        assert "1 dashboard process(es) stopped" in result.output

    def test_port_not_found_exits_nonzero(self):
        runner = CliRunner()
        procs = [_proc(1111, 8787, "/tmp/a")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs), \
             patch("os.kill"):
            result = runner.invoke(main, ["dashboard-kill", "--port", "9999"])
        assert result.exit_code != 0
        assert "No dashboard found on port 9999" in result.output

    def test_port_not_found_shows_running_ports(self):
        runner = CliRunner()
        procs = [_proc(1111, 8787, "/tmp/a")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs), \
             patch("os.kill"):
            result = runner.invoke(main, ["dashboard-kill", "--port", "9999"])
        assert "8787" in result.output


# ─── AC5: dashboard-kill output hints user to run shux dashboard-list ─────────────

class TestDashboardKillHints:
    def test_hint_to_list_remaining_after_kill(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[_proc()]), \
             patch("os.kill"):
            result = runner.invoke(main, ["dashboard-kill"])
        assert "shux dashboard-list" in result.output

    def test_no_hint_when_nothing_killed(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[_proc()]), \
             patch("os.kill", side_effect=ProcessLookupError):
            result = runner.invoke(main, ["dashboard-kill"])
        # killed == 0 so no "list remaining" hint
        assert "list remaining" not in result.output

    def test_not_found_no_processes_shows_list_hint(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-kill"])
        assert "shux dashboard-list" in result.output


# ─── AC6: dashboard-list when nothing running prints "No dashboard-ui processes" ──

class TestDashboardListEmpty:
    def test_empty_list_prints_no_processes_message(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "No dashboard processes running" in result.output

    def test_empty_list_no_table_header(self):
        runner = CliRunner()
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-list"])
        # No table header when empty
        assert "-----" not in result.output
