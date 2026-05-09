import pytest
import os
import yaml
import json
import subprocess
import sys
from unittest.mock import MagicMock, patch
from superharness.commands.inbox_dispatch import _do_dispatch, _MkdirLock

@pytest.fixture
def temp_project(tmp_path):
    sh_dir = tmp_path / ".superharness"
    sh_dir.mkdir()
    
    # Create inbox.yaml
    with open(sh_dir / "inbox.yaml", "w") as f:
        f.write("# Delegation inbox\n")
        
    # Create contract.yaml (empty, as in sqlite_only mode)
    with open(sh_dir / "contract.yaml", "w") as f:
        f.write("")
        
    return tmp_path

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_reconcile_review_requested_to_done(temp_project):
    sh_dir = temp_project / ".superharness"
    inbox_file = sh_dir / "inbox.yaml"
    contract_file = sh_dir / "contract.yaml"
    
    # Add launched item to inbox
    item_id = "test-item"
    inbox = [
        {
            "id": item_id,
            "task": "feat-1",
            "to": "claude-code",
            "status": "launched",
            "created_at": "2026-04-28T12:00:00Z"
        }
    ]
    with open(inbox_file, "w") as f:
        f.write("# Delegation inbox\n")
        yaml.dump(inbox, f)
        
    # Mock state_reader to return 'review_requested' for the task
    with patch("superharness.engine.state_reader.get_tasks") as mock_get_tasks:
        mock_get_tasks.return_value = [
            {"id": "feat-1", "status": "review_requested"}
        ]
        
        with patch("superharness.commands.inbox_dispatch._now_utc") as mock_now:
            mock_now.return_value = "2026-04-28T13:00:00Z"
            
            # Mock lock
            lock = MagicMock(spec=_MkdirLock)
            lock.acquire_with_retry.return_value = True
            
            with patch("superharness.engine.adapter_registry.resolve_launcher") as mock_res:
                mock_res.return_value = "launcher.sh"
                
                with patch("superharness.commands.inbox_dispatch._has_dirty_worktree") as mock_dirty:
                    mock_dirty.return_value = False
                    with patch("superharness.commands.inbox_dispatch._git_worktree_add") as mock_wt:
                        mock_wt.return_value = None
                        
                        # Mock subprocess.run
                        def mock_run_side_effect(args, **kwargs):
                            cmd = " ".join(args) if isinstance(args, list) else str(args)
                            if "next_pending" in cmd:
                                return MagicMock(returncode=0, stdout=json.dumps(inbox[0]))
                            if "launch" in cmd:
                                return MagicMock(returncode=0, stdout="retry_count=0")
                            if "task_status" in cmd:
                                return MagicMock(returncode=0, stdout="review_requested")
                            return MagicMock(returncode=0, stdout="")

                        with patch("subprocess.run", side_effect=mock_run_side_effect) as mock_run:
                            # Mock Popen
                            with patch("subprocess.Popen") as mock_popen:
                                p_inst = mock_popen.return_value
                                p_inst.pid = 1234
                                p_inst.wait.return_value = 0

                                _do_dispatch(
                                    inbox_file=str(inbox_file),
                                    contract_file=str(contract_file),
                                    project_dir=str(temp_project),
                                    target_filter=None,
                                    non_interactive=True,
                                    print_only=False,
                                    codex_bypass=False,
                                    launcher_timeout=0,
                                    script_dir=".",
                                    lock=lock,
                                    sqlite_primary=True # Test the new SQLite path
                                )
                                
                                # Verify inbox was updated to 'done'
                                with open(inbox_file, "r") as f:
                                    items = yaml.safe_load(f)
                                    assert items[0]["status"] == "done"
                                    assert items[0]["done_at"] == "2026-04-28T13:00:00Z"

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_reconcile_review_failed_to_todo(temp_project):
    sh_dir = temp_project / ".superharness"
    inbox_file = sh_dir / "inbox.yaml"
    contract_file = sh_dir / "contract.yaml"
    
    # Add launched item to inbox
    item_id = "test-item-3"
    inbox = [
        {
            "id": item_id,
            "task": "feat-1",
            "to": "claude-code",
            "status": "launched",
            "created_at": "2026-04-28T12:00:00Z"
        }
    ]
    with open(inbox_file, "w") as f:
        f.write("# Delegation inbox\n")
        yaml.dump(inbox, f)
        
    # Mock state_reader to return 'failed' for the task
    with patch("superharness.engine.state_reader.get_tasks") as mock_get_tasks:
        mock_get_tasks.return_value = [
            {"id": "feat-1", "status": "failed"}
        ]
        
        with patch("superharness.commands.inbox_dispatch._now_utc") as mock_now:
            mock_now.return_value = "2026-04-28T13:00:00Z"
            
            lock = MagicMock(spec=_MkdirLock)
            lock.acquire_with_retry.return_value = True
            
            with patch("superharness.engine.adapter_registry.resolve_launcher") as mock_res:
                mock_res.return_value = "launcher.sh"
                
                with patch("superharness.commands.inbox_dispatch._has_dirty_worktree") as mock_dirty:
                    mock_dirty.return_value = False
                    with patch("superharness.commands.inbox_dispatch._git_worktree_add") as mock_wt:
                        mock_wt.return_value = None
                        
                        def mock_run_side_effect(args, **kwargs):
                            cmd = " ".join(args) if isinstance(args, list) else str(args)
                            if "next_pending" in cmd:
                                return MagicMock(returncode=0, stdout=json.dumps(inbox[0]))
                            if "launch" in cmd:
                                return MagicMock(returncode=0, stdout="retry_count=0")
                            return MagicMock(returncode=0, stdout="")

                        with patch("subprocess.run", side_effect=mock_run_side_effect) as mock_run:
                            with patch("subprocess.Popen") as mock_popen:
                                p_inst = mock_popen.return_value
                                p_inst.pid = 1235
                                p_inst.wait.return_value = 0

                                _do_dispatch(
                                    inbox_file=str(inbox_file),
                                    contract_file=str(contract_file),
                                    project_dir=str(temp_project),
                                    target_filter=None,
                                    non_interactive=True,
                                    print_only=False,
                                    codex_bypass=False,
                                    launcher_timeout=0,
                                    script_dir=".",
                                    lock=lock,
                                    sqlite_primary=True
                                )
                                
                                with open(inbox_file, "r") as f:
                                    items = yaml.safe_load(f)
                                    assert items[0]["status"] == "failed"
                                    assert items[0]["failed_at"] == "2026-04-28T13:00:00Z"
