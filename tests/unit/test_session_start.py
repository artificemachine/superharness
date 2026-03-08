from __future__ import annotations

import json

from tests.helpers import run_bash


def test_session_start_outputs_json_with_context(repo_root, tmp_path) -> None:
    project = tmp_path / "proj"
    project.mkdir()
    superharness = project / ".superharness"
    (superharness / "handoffs").mkdir(parents=True)
    (superharness / "contract.yaml").write_text("id: x\n")
    (superharness / "handoffs/2026-01-demo.yaml").write_text("to: claude-code\n")

    script = repo_root / "adapters/claude-code/hooks/session-start.sh"
    result = run_bash(script, cwd=project)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "additionalContext" in payload
    context = payload["additionalContext"]
    assert "<superharness>" in context
    assert "Active contract found" in context
    assert "Pending handoff for you" in context
