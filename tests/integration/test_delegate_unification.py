import os
import subprocess
import pytest
from pathlib import Path

@pytest.fixture
def fake_adapter(tmp_path):
    # Setup a fake adapter manifest and launcher
    manifest_dir = Path("src/superharness/adapter_manifests")
    scripts_dir = Path("src/superharness/scripts")
    
    manifest_file = manifest_dir / "fake-agent.yaml"
    launcher_file = scripts_dir / "delegate-to-fake.sh"
    
    manifest_content = """name: fake-agent
version: "1"
description: "Fake agent for testing unification"
type: external
launcher_script: delegate-to-fake.sh
model_tiers:
  standard: { id: fake-model, label: "Fake Model" }
"""
    
    launcher_content = """#!/bin/bash
echo "FAKE_LAUNCHER_CALLED with args: $@"
exit 0
"""
    
    manifest_file.write_text(manifest_content)
    launcher_file.write_text(launcher_content)
    launcher_file.chmod(0o755)
    
    yield "fake-agent"
    
    # Cleanup
    if manifest_file.exists(): manifest_file.unlink()
    if launcher_file.exists(): launcher_file.unlink()

@pytest.mark.skip(reason="Uses live project contract — conflicts with real archived task state. Covered by test_delegate_unification_v2.py with proper mocking.")
def test_delegate_unification_uses_registry(fake_adapter):
    # Setup a temporary task in the contract
    task_id = "test-unification-task"
    subprocess.run(["shux", "task", "delete", "--id", task_id], check=False)
    subprocess.run(["shux", "task", "create", "--id", task_id, "--title", "Test Task", "--owner", "gemini-cli"], check=True)



    subprocess.run(["shux", "task", "status", "--id", task_id, "--status", "in_progress", "--actor", "gemini-cli", "--summary", "starting"], check=True)

    try:
        # This should now reach _launch_agent and call our fake script
        result = subprocess.run(
            ["shux", "delegate", "--to", "fake-agent", "--task", task_id],
            capture_output=True, text=True
        )
        
        # We want it to pass the hardcoded list check in main()
        # and then successfully resolve the launcher and call it.
        assert result.returncode == 0
        assert "Launching Fake-agent" in result.stdout
        assert "delegate-to-fake.sh" in result.stdout

    finally:

        # Cleanup task
        subprocess.run(["shux", "task", "delete", "--id", task_id], check=False)



