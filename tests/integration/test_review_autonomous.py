import pytest
import os
import yaml
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from superharness.commands.inbox_watch import _auto_close_review_passed

@pytest.fixture
def mock_project(tmp_path):
    project_dir = tmp_path
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    
    # Create profile.yaml with auto_close enabled
    with open(sh_dir / "profile.yaml", "w") as f:
        yaml.dump({"autonomy": "autonomous", "auto_close": True}, f)
        
    # Create contract.yaml
    contract = {
        "tasks": [
            {
                "id": "feat-test",
                "status": "review_requested",
                "owner": "author-agent",
                "model_tier": "standard"
            }
        ]
    }
    with open(sh_dir / "contract.yaml", "w") as f:
        yaml.dump(contract, f)
        
    # Create ledger.md
    with open(sh_dir / "ledger.md", "w") as f:
        f.write("# Ledger\n")
        
    return project_dir

def test_auto_close_lgtm_regex(mock_project):
    sh_dir = mock_project / ".superharness"
    inbox_file = sh_dir / "inbox.yaml"
    
    # Create an inbox item with a conversational LGTM
    outcome = "I have reviewed the changes. They look great!\nreview_verdict: lgtm\nGood job."
    inbox = [
        {
            "id": "item-1",
            "task": "feat-test",
            "to": "reviewer-agent",
            "status": "done",
            "outcome": outcome,
            "created_at": "2026-04-28T12:00:00Z"
        }
    ]
    with open(inbox_file, "w") as f:
        yaml.dump(inbox, f)
        
    with patch("superharness.commands.inbox_watch._load_tasks") as mock_load:
        mock_load.return_value = [{"id": "feat-test", "status": "review_requested"}]
        with patch("superharness.engine.state_reader.get_inbox_items") as mock_get_inbox:
            mock_get_inbox.return_value = inbox
            with patch("superharness.commands.close.close_task") as mock_close:
                with patch("superharness.engine.state_writer.set_task_status") as mock_set_status:
                    mock_set_status.return_value = True
                    
                    _auto_close_review_passed(str(mock_project))
                    
                    # Verify task status update was called
                    mock_set_status.assert_any_call(str(mock_project), "feat-test", "review_passed")
                    
                    # Verify close_task was called
                    mock_close.assert_called_once()
                    assert mock_close.call_args[1]["task_id"] == "feat-test"
                    assert "detected LGTM" in mock_close.call_args[1]["summary"]

def test_auto_close_rejected_regex(mock_project):
    sh_dir = mock_project / ".superharness"
    inbox_file = sh_dir / "inbox.yaml"
    
    # Create an inbox item with a conversational rejection
    outcome = "The implementation has some issues.\nverdict: rejected\nPlease fix the tests."
    inbox = [
        {
            "id": "item-2",
            "task": "feat-test",
            "to": "reviewer-agent",
            "status": "done",
            "outcome": outcome,
            "created_at": "2026-04-28T12:00:00Z"
        }
    ]
    with open(inbox_file, "w") as f:
        yaml.dump(inbox, f)
        
    with patch("superharness.commands.inbox_watch._load_tasks") as mock_load:
        mock_load.return_value = [{"id": "feat-test", "status": "review_requested"}]
        with patch("superharness.engine.state_reader.get_inbox_items") as mock_get_inbox:
            mock_get_inbox.return_value = inbox
            with patch("superharness.engine.state_writer.set_task_status") as mock_set_status:
                mock_set_status.return_value = True
                
                _auto_close_review_passed(str(mock_project))
                
                # Verify task status was updated to review_failed
                mock_set_status.assert_called_with(str(mock_project), "feat-test", "review_failed")
                
                # Verify ledger entry
                ledger = open(sh_dir / "ledger.md").read()
                assert "REJECTED: feat-test review failed by reviewer-agent" in ledger
