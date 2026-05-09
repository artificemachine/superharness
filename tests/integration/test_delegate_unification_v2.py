import os
import pytest
from unittest.mock import patch, MagicMock
from superharness.commands.delegate import delegate

@pytest.fixture
def dummy_project(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    harness_dir = project_dir / ".superharness"
    harness_dir.mkdir()
    handoff_dir = harness_dir / "handoffs"
    handoff_dir.mkdir()

    contract_file = harness_dir / "contract.yaml"
    contract_file.write_text("""
id: test-contract
tasks:
  - id: task-1
    title: Test Task
    owner: claude-code
    status: plan_approved
  - id: task-2
    title: Test Task 2
    owner: opencode
    status: plan_approved
  - id: task-3
    title: Test Task 3
    owner: gemini-cli
    status: plan_approved
  - id: task-4
    title: Test Task 4
    owner: codex-cli
    status: plan_approved
""")
    return project_dir

@patch("superharness.commands.delegate._cmd_exists", return_value=True)
@patch("superharness.engine.platform_runtime.launch_agent", return_value=0)
@patch("superharness.commands.delegate._rotate_launcher_logs")
@patch("superharness.commands.delegate.sdk_available", return_value=False)
@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_routing_unification(mock_sdk, mock_rotate, mock_launch, mock_exists, dummy_project):
    # All agents now route through bash + launcher script (unified dispatch)

    # claude-code: bash delegate-to-claude.sh
    with pytest.raises(SystemExit):
        delegate(str(dummy_project), "claude-code", "task-1", False, False, False)
    mock_launch.assert_called()
    args, _ = mock_launch.call_args
    assert args[0][0] == "bash"
    assert "delegate-to-claude.sh" in args[0][1]
    mock_launch.reset_mock()

    # opencode + model prefixing: bash delegate-to-opencode.sh --model anthropic/claude-sonnet
    with pytest.raises(SystemExit):
        delegate(str(dummy_project), "opencode", "task-2", False, False, False, model_override="claude-sonnet")
    args, _ = mock_launch.call_args
    assert args[0][0] == "bash"
    assert "delegate-to-opencode.sh" in args[0][1]
    assert "anthropic/claude-sonnet" in args[0]
    mock_launch.reset_mock()

    # gemini-cli: bash delegate-to-gemini.sh
    with pytest.raises(SystemExit):
        delegate(str(dummy_project), "gemini-cli", "task-3", False, False, False)
    args, _ = mock_launch.call_args
    assert args[0][0] == "bash"
    assert "delegate-to-gemini.sh" in args[0][1]
    mock_launch.reset_mock()

    # codex-cli: bash delegate-to-codex.sh
    with pytest.raises(SystemExit):
        delegate(str(dummy_project), "codex-cli", "task-4", False, False, False)
    args, _ = mock_launch.call_args
    assert args[0][0] == "bash"
    assert "delegate-to-codex.sh" in args[0][1]
