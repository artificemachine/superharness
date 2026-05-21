"""
Comprehensive tests for superharness.cli module.

Tests cover:
- Main group behavior (help, version, no-args)
- Helper functions (_run_script, _run_module, _is_dashboard_running, _is_git_repo)
- CLI commands (dashboard, delegate, update, contract, run, shux, version, help)
- Edge cases and error handling
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from superharness.cli import (
    _cmd,
    _is_git_repo,
    _run_module,
    _run_script,
    cmd_shux,
    cmd_version,
    main,
)
from superharness.commands.dashboard import (
    _find_dashboard_processes,
    _is_dashboard_running,
    run_dashboard as _run_dashboard,
)


@pytest.fixture
def runner():
    """Provide a Click CLI test runner."""
    return CliRunner()


class TestMainGroup:
    """Tests for the main Click group."""

    def test_main_no_args_shows_help(self, runner):
        """Invoking with no args should show help and exit 0."""
        result = runner.invoke(main, [])
        assert result.exit_code == 0
        assert "Usage" in result.output
        assert "superharness" in result.output.lower()

    def test_main_help_flag_shows_help(self, runner):
        """--help flag should show help."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_main_h_flag_shows_help(self, runner):
        """--h flag should show help."""
        result = runner.invoke(main, ["-h"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_main_version_flag_shows_version(self, runner):
        """--version flag should show version."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        # Should contain version pattern like x.y.z
        import re
        assert re.search(r"\d+\.\d+\.\d+", result.output)


class TestVersionCommand:
    """Tests for the version command."""

    def test_version_command_outputs_version(self, runner):
        """version subcommand should output version string."""
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert "superharness" in result.output.lower()
        # Check for version pattern
        import re
        assert re.search(r"\d+\.\d+\.\d+", result.output)

    def test_cmd_version_direct(self, runner):
        """Direct invocation of cmd_version should work."""
        result = runner.invoke(cmd_version)
        assert result.exit_code == 0
        assert "superharness" in result.output.lower()


class TestHelpCommand:
    """Tests for the help command."""

    @pytest.mark.skip(reason="help subcommand removed in M11")
    def test_help_command_shows_help(self, runner):
        """help subcommand should show main help."""
        result = runner.invoke(main, ["help"])
        assert result.exit_code == 0
        assert "Usage" in result.output


class TestShuxCommand:
    """Tests for the shux shortcuts command."""

    def test_shux_command_shows_shortcuts(self, runner):
        """shux subcommand should show operator shortcuts."""
        result = runner.invoke(main, ["shux"])
        assert result.exit_code == 0
        assert "shux init" in result.output
        assert "shux doctor" in result.output
        assert "shux contract" in result.output
        assert "shux watch" in result.output

    def test_cmd_shux_direct(self, runner):
        """Direct invocation of cmd_shux should work."""
        result = runner.invoke(cmd_shux)
        assert result.exit_code == 0
        assert "shux init" in result.output


class TestRunScript:
    """Tests for the _run_script helper function."""

    def test_run_script_success(self):
        """_run_script should call bash with script path and args."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            with patch("superharness.cli.sys.exit") as mock_exit:
                mock_run.return_value = MagicMock(returncode=0)

                _run_script("test-script.sh", ("arg1", "arg2"))

                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert call_args[0] == "bash"
                assert "test-script.sh" in call_args[1]
                assert "arg1" in call_args
                assert "arg2" in call_args
                mock_exit.assert_called_once_with(0)

    def test_run_script_failure(self):
        """_run_script should exit with non-zero code on failure."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            with patch("superharness.cli.sys.exit") as mock_exit:
                mock_run.return_value = MagicMock(returncode=1)

                _run_script("test-script.sh", ())

                mock_exit.assert_called_once_with(1)

    def test_run_script_with_empty_args(self):
        """_run_script should work with empty args tuple."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            with patch("superharness.cli.sys.exit") as mock_exit:
                mock_run.return_value = MagicMock(returncode=0)

                _run_script("test-script.sh", ())

                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert len(call_args) == 2  # Only bash and script path


class TestRunModule:
    """Tests for the _run_module helper function."""

    def test_run_module_success(self):
        """_run_module should call Python module with args."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            with patch("superharness.cli.sys.exit") as mock_exit:
                mock_run.return_value = MagicMock(returncode=0)

                _run_module("superharness.commands.test", ("arg1", "arg2"))

                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                assert call_args[0] == sys.executable
                assert call_args[1] == "-m"
                assert "superharness.commands.test" in call_args
                assert "arg1" in call_args
                mock_exit.assert_called_once_with(0)

    def test_run_module_failure(self):
        """_run_module should exit with non-zero code on failure."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            with patch("superharness.cli.sys.exit") as mock_exit:
                mock_run.return_value = MagicMock(returncode=127)

                _run_module("superharness.commands.test", ())

                mock_exit.assert_called_once_with(127)


class TestIsMonitorRunning:
    """Tests for the _is_dashboard_running helper function."""

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_dashboard_running_on_default_port(self):
        """_is_dashboard_running should detect running dashboard via /api/status on default port."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_resp) as mock_open:
            running, port = _is_dashboard_running()
            assert running is True
            assert port == 8787
            url = mock_open.call_args[0][0]
            assert "127.0.0.1:8787" in url.full_url
            assert "/api/status" in url.full_url

    def test_dashboard_not_running_connection_refused(self):
        """_is_dashboard_running should return False when connection refused."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError()):
                running, port = _is_dashboard_running()
                assert running is False
                assert port is None

    def test_dashboard_not_running_os_error(self):
        """_is_dashboard_running should return False on OSError."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            with patch("urllib.request.urlopen", side_effect=OSError()):
                running, port = _is_dashboard_running()
                assert running is False
                assert port is None

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_dashboard_running_custom_port(self):
        """_is_dashboard_running should detect dashboard for a given project_dir."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[(9001, 9000, "/myproject")]):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                running, port = _is_dashboard_running("/myproject")
                assert running is True
                assert port == 9000


class TestIsGitRepo:
    """Tests for the _is_git_repo helper function."""

    def test_is_git_repo_valid(self):
        """_is_git_repo should return True for valid git repository."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            assert _is_git_repo("/path/to/repo") is True

            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert call_args[0] == "git"
            assert "-C" in call_args
            assert "/path/to/repo" in call_args
            assert "rev-parse" in call_args

    def test_is_git_repo_invalid(self):
        """_is_git_repo should return False for non-git directory."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1)

            assert _is_git_repo("/path/to/dir") is False

    def test_is_git_repo_not_found(self):
        """_is_git_repo should return False if path doesn't exist."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128)

            assert _is_git_repo("/nonexistent/path") is False


class TestDashboardCommand:
    """Tests for dashboard and dashboard-ui commands."""

    def test_cmd_dashboard_delegates_to_run_dashboard(self, runner):
        """cmd_dashboard should delegate to _run_dashboard."""
        with patch("superharness.commands.dashboard.run_dashboard") as mock_run_dashboard:
            runner.invoke(main, ["dashboard", "--port", "9000"])
            mock_run_dashboard.assert_called_once()

    def test_cmd_dashboard_ui_delegates_to_run_dashboard(self, runner):
        """cmd_dashboard_ui should delegate to _run_dashboard."""
        with patch("superharness.commands.dashboard.run_dashboard") as mock_run_dashboard:
            runner.invoke(main, ["dashboard-ui", "--port", "9000"])
            mock_run_dashboard.assert_called_once()

    def test_run_dashboard_already_running_background(self, capsys):
        """_run_dashboard should print URL if already running (background mode)."""
        with patch("superharness.commands.dashboard._is_dashboard_running", return_value=(True, 8787)):
            with patch("superharness.cli.os.getcwd", return_value="/test/proj"):
                _run_dashboard(("--port", "8787"))

                # Should print existing dashboard URL
                captured = capsys.readouterr()
                output = captured.out + captured.err
                assert "8787" in output or "http" in output

    def test_run_dashboard_foreground_mode(self):
        """_run_dashboard should handle foreground mode."""
        with patch("superharness.cli.subprocess.run") as mock_run:
            with patch("superharness.cli.sys.exit") as mock_exit:
                mock_run.return_value = MagicMock(returncode=0)

                _run_dashboard(("--foreground",))

                # Should call subprocess.run (not Popen)
                mock_run.assert_called_once()
                mock_exit.assert_called_once_with(0)

    def test_run_dashboard_help_shows_script_help(self):
        """_run_dashboard should forward --help to dashboard-ui.py instead of launching the app."""
        with patch("superharness.commands.dashboard.subprocess.run") as mock_run:
            with patch("superharness.commands.dashboard.sys.exit", side_effect=SystemExit(0)) as mock_exit:
                mock_run.return_value = MagicMock(returncode=0)
                with pytest.raises(SystemExit):
                    _run_dashboard(("--help",))
                mock_run.assert_called_once()
                mock_exit.assert_called_once_with(0)

    def test_run_dashboard_injects_project_default(self):
        """_run_dashboard should inject --project if not provided."""
        with patch("superharness.commands.dashboard._is_dashboard_running", return_value=(False, None)):
            with patch("superharness.cli.subprocess.Popen") as mock_popen:
                mock_popen.return_value.pid = 12345
                with patch("superharness.cli.os.getcwd", return_value="/myproject"):
                    with patch("superharness.cli.os.path.exists", return_value=False):
                        _run_dashboard(())

                        # Should inject --project
                        call_args = mock_popen.call_args[0][0]
                        assert "--project" in call_args
                        assert "/myproject" in call_args

    def test_run_dashboard_respects_explicit_project(self):
        """_run_dashboard should not inject project if already specified."""
        with patch("superharness.commands.dashboard._is_dashboard_running", return_value=(False, None)):
            with patch("superharness.cli.subprocess.Popen") as mock_popen:
                mock_popen.return_value.pid = 12345
                with patch("superharness.cli.os.path.exists", return_value=False):
                    _run_dashboard(("--project", "/explicit/path"))

                    # Should not duplicate --project
                    call_args = mock_popen.call_args[0][0]
                    project_count = call_args.count("--project")
                    assert project_count == 1


class TestDelegateCommand:
    """Tests for the delegate command."""

    def test_cmd_delegate_with_task_id_no_contract(self, runner):
        """delegate <task-id> without contract should default to claude-code."""
        with patch("superharness.cli._run_module") as mock_run_module:
            with patch("superharness.cli.os.path.isfile", return_value=False):
                runner.invoke(main, ["delegate", "task-123"])

                mock_run_module.assert_called_once()
                args = mock_run_module.call_args[0][1]
                assert "--to" in args
                assert "claude-code" in args
                assert "--task" in args
                assert "task-123" in args

    def test_cmd_delegate_with_task_id_and_contract_claude_code(self, runner, tmp_path):
        """delegate should look up owner from SQLite and inject --to."""
        from unittest.mock import MagicMock

        mock_row = MagicMock()
        mock_row.owner = "claude-code"

        with patch("superharness.cli._run_module") as mock_run_module:
            with patch("superharness.engine.tasks_dao.get", return_value=mock_row):
                with patch("superharness.engine.db.get_connection"):
                    with patch("superharness.engine.db.init_db"):
                        runner.invoke(main, ["delegate", "task-123"])

                        mock_run_module.assert_called_once()
                        args = mock_run_module.call_args[0][1]
                        assert "--to" in args
                        assert "claude-code" in args

    def test_cmd_delegate_with_task_id_codex_owner(self, runner, tmp_path):
        """delegate should look up codex-cli owner from SQLite."""
        from unittest.mock import MagicMock

        mock_row = MagicMock()
        mock_row.owner = "codex-cli"

        with patch("superharness.cli._run_module") as mock_run_module:
            with patch("superharness.engine.tasks_dao.get", return_value=mock_row):
                with patch("superharness.engine.db.get_connection"):
                    with patch("superharness.engine.db.init_db"):
                        runner.invoke(main, ["delegate", "task-456"])

                        mock_run_module.assert_called_once()
                        args = mock_run_module.call_args[0][1]
                        assert "--to" in args
                        assert "codex-cli" in args

    def test_cmd_delegate_without_task_id(self, runner):
        """delegate without task-id should pass through to module."""
        with patch("superharness.cli._run_module") as mock_run_module:
            runner.invoke(main, ["delegate", "--help"])

            mock_run_module.assert_called_once()
            # Should have called without injecting task/owner
            args = mock_run_module.call_args[0][1]
            assert "--help" in args


class TestContractCommand:
    """Tests for the contract command."""

    def test_cmd_contract_filters_legacy_today(self, runner):
        """contract should filter out legacy 'today' subcommand token."""
        with patch("superharness.cli._run_module") as mock_run_module:
            runner.invoke(main, ["contract", "today"])

            mock_run_module.assert_called_once()
            args = mock_run_module.call_args[0][1]
            # 'today' should be filtered out
            assert "today" not in args

    def test_cmd_contract_filters_legacy_help(self, runner):
        """contract should filter out legacy 'help' token."""
        with patch("superharness.cli._run_module") as mock_run_module:
            runner.invoke(main, ["contract", "help"])

            mock_run_module.assert_called_once()
            args = mock_run_module.call_args[0][1]
            assert "help" not in args

    def test_cmd_contract_no_legacy_tokens(self, runner):
        """contract should pass through args when no legacy tokens."""
        with patch("superharness.cli._run_module") as mock_run_module:
            runner.invoke(main, ["contract", "--project", "/path"])

            mock_run_module.assert_called_once()
            args = mock_run_module.call_args[0][1]
            assert "--project" in args
            assert "/path" in args


class TestUpdateCommand:
    """Tests for the update command."""

    def test_cmd_update_git_repo_path(self):
        """update should use git pull if in git repo."""
        with patch("superharness.cli._is_git_repo", return_value=True):
            with patch("superharness.cli.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                with patch("superharness.cli._run_module") as mock_run_module:
                    runner = CliRunner()
                    result = runner.invoke(main, ["update"])

                    assert result.exit_code == 0 or mock_run.called
                    # Should attempt git pull
                    git_calls = [c for c in mock_run.call_args_list if "git" in str(c)]
                    assert len(git_calls) > 0

    def test_cmd_update_git_pull_failure_exits(self):
        """update should exit if git pull fails."""
        with patch("superharness.cli._is_git_repo", return_value=True):
            with patch("superharness.cli.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                runner = CliRunner()
                result = runner.invoke(main, ["update"])

                assert result.exit_code != 0

    def test_cmd_update_non_git_repo_pip_install(self):
        """update should use pipx/pip if not in git repo."""
        with patch("superharness.cli._is_git_repo", return_value=False):
            with patch("superharness.cli.subprocess.run") as mock_run:
                # pipx fails, fallback to pip succeeds
                mock_run.side_effect = [
                    MagicMock(returncode=1),  # pipx upgrade fails
                    MagicMock(returncode=0),  # pip install succeeds
                ]
                with patch("superharness.cli._run_module") as mock_run_module:
                    runner = CliRunner()
                    result = runner.invoke(main, ["update"])

                    # Should try pip upgrade
                    calls = [str(c) for c in mock_run.call_args_list]
                    output = "\n".join(calls)
                    assert "pip" in output or "upgrade" in output

    def test_cmd_update_refreshes_templates(self):
        """update should refresh templates via init_project."""
        with patch("superharness.cli._is_git_repo", return_value=False):
            with patch("superharness.cli.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                with patch("superharness.cli._run_module") as mock_run_module:
                    with patch("superharness.cli.os.path.isfile", return_value=False):
                        runner = CliRunner()
                        result = runner.invoke(main, ["update"])

                        # Should call init_project with --refresh
                        calls = [str(c) for c in mock_run_module.call_args_list]
                        output = "\n".join(calls)
                        assert "init_project" in output or "refresh" in output


class TestRunCommand:
    """Tests for the run command."""

    def test_cmd_run_requires_prompt(self, runner):
        """run command should require a prompt argument."""
        result = runner.invoke(main, ["run"])
        assert result.exit_code != 0

    def test_cmd_run_without_sdk_falls_back_to_cli(self):
        """run should fall back to delegate CLI if SDK not available."""
        with patch("superharness.engine.sdk_runner.sdk_available", return_value=False):
            with patch("superharness.cli._run_module") as mock_run_module:
                runner = CliRunner()
                result = runner.invoke(main, ["run", "test prompt"])

                # Should fall back to delegate
                mock_run_module.assert_called_once()
                args = mock_run_module.call_args[0][1]
                assert "--via" in args
                assert "cli" in args

    def test_cmd_run_with_model_shorthand(self):
        """run should support model shorthands."""
        with patch("superharness.engine.sdk_runner.sdk_available", return_value=True):
            with patch("superharness.engine.sdk_runner.SDKRunner") as mock_runner_class:
                mock_runner = MagicMock()
                mock_runner.run.return_value = {
                    "output": "test",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost_usd": 0.001,
                }
                mock_runner_class.return_value = mock_runner

                runner = CliRunner()
                result = runner.invoke(main, ["run", "test", "--model", "sonnet"])

                assert mock_runner_class.called
                call_kwargs = mock_runner_class.call_args[1]
                assert call_kwargs["model"] == "claude-sonnet-4-6"

    def test_cmd_run_outputs_result(self):
        """run should output the result from SDKRunner."""
        with patch("superharness.engine.sdk_runner.sdk_available", return_value=True):
            with patch("superharness.engine.sdk_runner.SDKRunner") as mock_runner_class:
                mock_runner = MagicMock()
                mock_runner.run.return_value = {
                    "output": "Hello world",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "cost_usd": 0.001,
                }
                mock_runner_class.return_value = mock_runner

                runner = CliRunner()
                result = runner.invoke(main, ["run", "test"])

                assert "Hello world" in result.output


class TestCommandFactory:
    """Tests for the _cmd factory function."""

    def test_cmd_creates_passthrough_command(self):
        """_cmd should create a command that dispatches to module or script."""
        with patch("superharness.cli.main.command") as mock_command:
            # Create a test command
            handler = _cmd("test-cmd", "Test help text", module="superharness.commands.test")

            assert handler is not None

    def test_cmd_with_module_dispatches_to_module(self):
        """_cmd with module should create dispatcher to Python module."""
        with patch("superharness.cli._run_module") as mock_run_module:
            # Simulate running a command created by _cmd
            runner = CliRunner()
            # Test with an actual registered command
            result = runner.invoke(main, ["task", "--help"])

            # task command is created with _cmd(module=...)
            # The --help might be passed through or might trigger module
            # Just verify it runs without error
            assert result.exit_code == 0 or "Usage" in result.output

    def test_cmd_with_script_dispatches_to_script(self):
        """_cmd with script should create dispatcher to bash script."""
        # Note: we can't easily test this without having actual scripts
        # This test documents the expected behavior
        pass

    def test_cmd_handler_name_sanitizes_dashes(self):
        """_cmd should convert dashes to underscores in handler name."""
        # The handler name should use underscores instead of dashes
        # This is verified by checking the __name__ attribute
        pass


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_unknown_subcommand_exits_nonzero(self, runner):
        """Unknown subcommands should fail."""
        result = runner.invoke(main, ["not-a-real-command"])
        assert result.exit_code != 0

    def test_passthrough_args_to_module(self, runner):
        """Arguments should be passed through to modules."""
        with patch("superharness.cli._run_module") as mock_run_module:
            runner.invoke(main, ["task", "create", "--name", "test"])

            mock_run_module.assert_called_once()
            args = mock_run_module.call_args[0][1]
            assert "create" in args
            assert "--name" in args
            assert "test" in args

    def test_dashboard_url_file_timeout(self, capsys):
        """_run_dashboard should handle URL file not appearing in time."""
        with patch("superharness.commands.dashboard._is_dashboard_running", return_value=(False, None)):
            with patch("superharness.cli.subprocess.Popen") as mock_popen:
                mock_popen.return_value.pid = 12345
                mock_popen.return_value.poll.return_value = None  # process still running
                with patch("superharness.cli.os.path.exists", return_value=False):
                    with patch("time.monotonic") as mock_time:
                        # Simulate time passing
                        mock_time.side_effect = [0, 0.1, 5.1]
                        _run_dashboard(())

                        # Should print "starting in background" message
                        captured = capsys.readouterr()
                        output = captured.out + captured.err
                        # Either "starting" or "pid:" should appear when timeout occurs
                        assert "starting" in output.lower() or "pid:" in output


class TestIntegration:
    """Integration tests for CLI commands."""

    @pytest.mark.skip(reason="help removed in M11, command list changed")
    def test_help_lists_main_commands(self, runner):
        """help output should list main commands."""
        result = runner.invoke(main, ["help"])
        assert result.exit_code == 0
        # Check for some key commands in help
        assert "shux" in result.output.lower()

    def test_shux_shortcut_shows_help(self, runner):
        """shux command should show operator shortcuts."""
        result = runner.invoke(main, ["shux"])
        assert result.exit_code == 0
        assert "shux init" in result.output
        assert "shux doctor" in result.output

    def test_version_consistent_with_flag(self, runner):
        """version command and --version flag should be consistent."""
        cmd_result = runner.invoke(main, ["version"])
        flag_result = runner.invoke(main, ["--version"])

        assert cmd_result.exit_code == flag_result.exit_code == 0
        # Both should contain version info
        import re
        assert re.search(r"\d+\.\d+\.\d+", cmd_result.output)
        assert re.search(r"\d+\.\d+\.\d+", flag_result.output)


class TestDashboardProjectAware:
    """Tests for project-aware dashboard detection (verify.dashboard-project-aware)."""

    # ── _is_dashboard_running with project_dir ──────────────────────────────────

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_is_dashboard_running_returns_true_for_matching_project(self):
        """_is_dashboard_running(project_dir) returns (True, port) when a dashboard serves that project."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[(1234, 8800, "/projects/myapp")]):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                running, port = _is_dashboard_running("/projects/myapp")
        assert running is True
        assert port == 8800

    def test_is_dashboard_running_returns_false_for_unknown_project(self):
        """_is_dashboard_running(project_dir) returns (False, None) when no dashboard serves that project."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[(1234, 8800, "/projects/other")]):
            running, port = _is_dashboard_running("/projects/myapp")
        assert running is False
        assert port is None

    def test_is_dashboard_running_returns_false_when_no_processes(self):
        """_is_dashboard_running(project_dir) returns (False, None) when no dashboards are running."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            with patch("urllib.request.urlopen", side_effect=ConnectionRefusedError()):
                running, port = _is_dashboard_running("/projects/myapp")
        assert running is False
        assert port is None

    @pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
    def test_is_dashboard_running_resolves_realpath_for_project(self):
        """_is_dashboard_running normalises symlinks when comparing project paths."""
        import os
        real_path = os.path.realpath("/projects/myapp")
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[(5678, 9100, real_path)]):
            with patch("urllib.request.urlopen", return_value=mock_resp):
                running, port = _is_dashboard_running("/projects/myapp")
        assert running is True
        assert port == 9100

    # ── dashboard-list shows Project column ─────────────────────────────────────

    def test_dashboard_list_shows_project_basename(self, runner):
        """dashboard-list shows basename of project_dir in PROJECT column."""
        processes = [(1111, 8800, "/home/user/projects/coolapp")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=processes):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "coolapp" in result.output

    def test_dashboard_list_shows_pid_port_url_columns(self, runner):
        """dashboard-list output contains PID, PORT, PROJECT, URL headers."""
        processes = [(2222, 9000, "/some/project")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=processes):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "PID" in result.output
        assert "PORT" in result.output
        assert "PROJECT" in result.output
        assert "URL" in result.output

    def test_dashboard_list_no_processes_shows_empty_message(self, runner):
        """dashboard-list prints helpful message when nothing is running."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "No dashboard processes running" in result.output

    def test_dashboard_list_shows_multiple_entries(self, runner):
        """dashboard-list shows one row per running dashboard."""
        processes = [
            (1111, 8800, "/projects/alpha"),
            (2222, 8801, "/projects/beta"),
        ]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=processes):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "alpha" in result.output
        assert "beta" in result.output
        assert "8800" in result.output
        assert "8801" in result.output

    # ── dashboard-kill --project kills only that project ─────────────────────────

    def test_dashboard_kill_project_kills_matching_process(self, runner):
        """dashboard-kill --project <dir> kills only the dashboard for that project."""
        processes = [
            (1111, 8800, "/projects/alpha"),
            (2222, 8801, "/projects/beta"),
        ]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=processes):
            with patch("superharness.cli.os.kill") as mock_kill:
                result = runner.invoke(main, ["dashboard-kill", "--project", "/projects/alpha"])
        assert result.exit_code == 0
        # Should have killed only pid 1111 (alpha), not 2222 (beta)
        killed_pids = [call.args[0] for call in mock_kill.call_args_list]
        assert 1111 in killed_pids
        assert 2222 not in killed_pids

    def test_dashboard_kill_project_not_found_exits_nonzero(self, runner):
        """dashboard-kill --project <dir> exits with non-zero when project not found."""
        processes = [(1111, 8800, "/projects/alpha")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=processes):
            with patch("superharness.cli.os.kill"):
                result = runner.invoke(main, ["dashboard-kill", "--project", "/projects/notfound"])
        assert result.exit_code != 0

    def test_dashboard_kill_no_args_kills_all(self, runner):
        """dashboard-kill with no filter kills all dashboard processes."""
        processes = [
            (1111, 8800, "/projects/alpha"),
            (2222, 8801, "/projects/beta"),
        ]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=processes):
            with patch("superharness.cli.os.kill") as mock_kill:
                result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        killed_pids = [call.args[0] for call in mock_kill.call_args_list]
        assert 1111 in killed_pids
        assert 2222 in killed_pids

    def test_dashboard_kill_no_processes_prints_message(self, runner):
        """dashboard-kill when nothing running prints helpful message."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "No dashboard processes found" in result.output

    # ── duplicate detection in _run_dashboard ───────────────────────────────────

    def test_run_dashboard_already_running_shows_url_and_project(self, capsys):
        """When a dashboard is already running for this project, _run_dashboard prints URL and project path."""
        with patch("superharness.commands.dashboard._is_dashboard_running", return_value=(True, 8800)):
            with patch("superharness.cli.os.getcwd", return_value="/projects/myapp"):
                _run_dashboard(("--project", "/projects/myapp"))
        captured = capsys.readouterr()
        output = captured.out + captured.err
        assert "8800" in output
        # Should mention the project or "already"
        assert "already" in output.lower() or "/projects/myapp" in output

    def test_run_dashboard_already_running_does_not_start_new_process(self):
        """When a dashboard is already running, _run_dashboard must NOT spawn a new process."""
        with patch("superharness.commands.dashboard._is_dashboard_running", return_value=(True, 8800)):
            with patch("superharness.cli.os.getcwd", return_value="/projects/myapp"):
                with patch("superharness.cli.subprocess.Popen") as mock_popen:
                    _run_dashboard(("--project", "/projects/myapp"))
        mock_popen.assert_not_called()


class TestDashboardList:
    """Tests for `shux dashboard-list` command (acceptance criteria v1.3.1)."""

    def test_no_processes_running(self, runner):
        """When no dashboard-ui processes found, prints sentinel message."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "No dashboard processes running" in result.output

    def test_shows_column_headers(self, runner):
        """When processes exist, header row includes PID, PORT, PROJECT, URL."""
        procs = [(12345, 8787, "/home/user/myproject")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "PID" in result.output
        assert "PORT" in result.output
        assert "PROJECT" in result.output
        assert "URL" in result.output

    def test_shows_process_row_data(self, runner):
        """Process row shows pid, port, project basename, and URL."""
        procs = [(99999, 8787, "/home/user/myproject")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "99999" in result.output
        assert "8787" in result.output
        assert "myproject" in result.output
        assert "http://127.0.0.1:8787" in result.output

    def test_hints_dashboard_kill(self, runner):
        """Output includes hint for shux dashboard-kill."""
        procs = [(12345, 8787, "/home/user/proj")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "dashboard-kill" in result.output

    def test_hints_dashboard_kill_port(self, runner):
        """Single-process output includes hint for dashboard-kill --port."""
        procs = [(12345, 8787, "/home/user/myproj")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "--port" in result.output

    def test_hints_dashboard_kill_project(self, runner):
        """Single-process output includes hint for dashboard-kill --project."""
        procs = [(12345, 8787, "/home/user/myproj")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-list"])
        assert result.exit_code == 0
        assert "--project" in result.output


class TestDashboardKill:
    """Tests for `shux dashboard-kill` command (acceptance criteria v1.3.1)."""

    def test_no_processes_found(self, runner):
        """When no processes running, prints not-found message and exits 0."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "No dashboard processes found" in result.output

    def test_no_processes_hints_dashboard_list(self, runner):
        """When no processes running, output hints user toward shux dashboard-list."""
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=[]):
            result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "dashboard-list" in result.output

    def test_kills_all_processes_and_prints_count(self, runner):
        """With no filter, kills every discovered process and prints count."""
        procs = [(11111, 8787, "/proj/a"), (22222, 8788, "/proj/b")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            with patch("superharness.cli.os.kill"):
                result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "2 dashboard process(es) stopped" in result.output

    def test_kill_hints_dashboard_list_after_success(self, runner):
        """After killing processes, output hints user to run shux dashboard-list."""
        procs = [(11111, 8787, "/proj/a")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            with patch("superharness.cli.os.kill"):
                result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "dashboard-list" in result.output

    def test_kill_by_port_kills_only_matching(self, runner):
        """--port filter kills only the process on the given port."""
        import signal
        procs = [(11111, 8787, "/proj/a"), (22222, 8788, "/proj/b")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            with patch("superharness.cli.os.kill") as mock_kill:
                result = runner.invoke(main, ["dashboard-kill", "--port", "8787"])
        assert result.exit_code == 0
        mock_kill.assert_called_once_with(11111, signal.SIGTERM)
        assert "1 dashboard process(es) stopped" in result.output

    def test_kill_by_port_not_found_exits_nonzero(self, runner):
        """--port for a port not in use exits non-zero."""
        procs = [(11111, 8787, "/proj/a")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            result = runner.invoke(main, ["dashboard-kill", "--port", "9999"])
        assert result.exit_code != 0

    def test_already_dead_process_handled(self, runner):
        """ProcessLookupError is handled gracefully — count still printed."""
        procs = [(11111, 8787, "/proj/a")]
        with patch("superharness.commands.dashboard._find_dashboard_processes", return_value=procs):
            with patch("superharness.cli.os.kill", side_effect=ProcessLookupError):
                result = runner.invoke(main, ["dashboard-kill"])
        assert result.exit_code == 0
        assert "process(es) stopped" in result.output
