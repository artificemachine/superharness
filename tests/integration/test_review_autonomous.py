import pytest
import os
import yaml
import re
from datetime import datetime, timezone
from superharness.commands.inbox_watch import _auto_close_review_passed
from superharness.engine.state_writer import mirror_task_dict
from superharness.engine import state_reader as _sr

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
        
    # Run watcher logic
    # We need to mock _load_tasks and _sr.get_inbox_items since we are using YAML in this test
    # but the logic might try to use SQLite if enabled.
    
    # For simplicity, we'll just mock the state_reader to return our YAML data
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("superharness.commands.inbox_watch._load_tasks", lambda p: yaml.safe_load(open(sh_dir / "contract.yaml")).get("tasks"))
        mp.setattr("superharness.engine.state_reader.get_inbox_items", lambda p: yaml.safe_load(open(inbox_file)))
        
        # Mock close_task to avoid actual closing
        from unittest.mock import MagicMock
        mock_close = MagicMock()
        mp.setattr("superharness.commands.inbox_watch.close_task", mock_close)
        
        _auto_close_review_passed(str(mock_project))
        
        # Verify task status was updated to review_passed
        tasks = yaml.safe_load(open(sh_dir / "contract.yaml")).get("tasks")
        assert tasks[0]["status"] == "review_passed"
        
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
        
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("superharness.commands.inbox_watch._load_tasks", lambda p: yaml.safe_load(open(sh_dir / "contract.yaml")).get("tasks"))
        mp.setattr("superharness.engine.state_reader.get_inbox_items", lambda p: yaml.safe_load(open(inbox_file)))
        
        _auto_close_review_passed(str(mock_project))
        
        # Verify task status was updated to review_failed
        tasks = yaml.safe_load(open(sh_dir / "contract.yaml")).get("tasks")
        assert tasks[0]["status"] == "review_failed"
        
        # Verify ledger entry
        ledger = open(sh_dir / "ledger.md").read()
        assert "REJECTED: feat-test review failed by reviewer-agent" in ledger
