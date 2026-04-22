import os
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from superharness.commands.delegate import delegate

def test_delegate_sdk_logic_claude_vs_others(tmp_path):
    """Verify that only claude-code attempts to use the SDK path."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    (sh_dir / "handoffs").mkdir()
    
    contract = {
        "id": "test-contract",
        "tasks": [
            {"id": "task-1", "status": "plan_approved", "owner": "claude-code", "project_path": str(project_dir)},
            {"id": "task-2", "status": "plan_approved", "owner": "gemini-cli", "project_path": str(project_dir)}
        ]
    }
    (sh_dir / "contract.yaml").write_text(yaml.dump(contract))
    
    # Mock SDK presence
    with patch("superharness.commands.delegate.sdk_available", return_value=True), \
         patch("superharness.commands.delegate.SDKRunner") as mock_runner, \
         patch("superharness.commands.delegate._launch_agent") as mock_launch:
        
        # 1. Claude-code SHOULD use SDK
        delegate(str(project_dir), "claude-code", "task-1", print_only=False, non_interactive=True, codex_bypass=False, skip_preflight=True)
        assert mock_runner.called, "SDKRunner should be called for claude-code"
        
        mock_runner.reset_mock()
        mock_launch.reset_mock()
        
        # 2. Gemini-cli should NOT use SDK
        delegate(str(project_dir), "gemini-cli", "task-2", print_only=False, non_interactive=True, codex_bypass=False, skip_preflight=True)
        assert not mock_runner.called, "SDKRunner should NOT be called for gemini-cli"
        assert mock_launch.called, "Should fallback to CLI (_launch_agent) for gemini-cli"

if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
