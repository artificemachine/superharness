from __future__ import annotations

import os
import pytest
import yaml
from pathlib import Path
from superharness.engine.adapter_registry import list_adapters, load_manifest, clear_manifest_cache
from superharness.engine.model_router import resolve_model
from superharness.commands.delegate import delegate

def _setup_minimal_project(tmp_path: Path):
    project = tmp_path / "multi_agent_proj"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir()
    (harness / "handoffs").mkdir()
    (harness / "launcher-logs").mkdir()
    
    contract = {
        "id": "multi-agent-test",
        "tasks": [
            {
                "id": "test-task",
                "title": "A generic test task",
                "status": "plan_approved",
                "owner": "placeholder",
                "project_path": str(project)
            }
        ]
    }
    (harness / "contract.yaml").write_text(yaml.dump(contract))
    (harness / "inbox.yaml").write_text("[]\n")
    return project

@pytest.mark.parametrize("agent_name", list_adapters())
def test_agent_lifecycle_compatibility(agent_name, tmp_path):
    """Verify that every registered agent can resolve models and generate prompts."""
    from superharness.engine.adapter_registry import MANIFEST_DIR
    print(f"DEBUG: MANIFEST_DIR={MANIFEST_DIR}")
    clear_manifest_cache()
    project = _setup_minimal_project(tmp_path)
    contract_file = project / ".superharness" / "contract.yaml"
    
    # 1. Update owner to the current agent under test
    content = yaml.safe_load(contract_file.read_text())
    content["tasks"][0]["owner"] = agent_name
    contract_file.write_text(yaml.dump(content))

    # 2. Verify Model Resolution (Standard Tier)
    # This caught the "Gemini defaulting to Sonnet" bug earlier.
    model = resolve_model(agent_name, "standard")
    manifest = load_manifest(agent_name)
    
    # Use the manifest's own resolution logic to verify
    expected = manifest.resolve_tier_version("standard")
    assert model == expected["id"], f"Agent '{agent_name}' resolved to model '{model}' but manifest standard tier is '{expected['id']}'"

    # 3. Verify Prompt Generation (Delegate)
    # This ensures prompt templates are defined for the agent.
    # We use print_only=True to avoid actual dispatch.
    import sys
    from io import StringIO
    
    _orig_stdout = sys.stdout
    sys.stdout = StringIO()
    try:
        rc = delegate(
            project_dir=str(project),
            target=agent_name,
            task_id="test-task",
            print_only=True,
            non_interactive=True,
            codex_bypass=False
        )
        output = sys.stdout.getvalue()
        assert rc == 0
        assert "Generated prompt:" in output
        assert "continue contract" in output
        # Verify the task ID appears in the prompt to ensure it is task-specific
        assert "test-task" in output
    finally:
        sys.stdout = _orig_stdout
