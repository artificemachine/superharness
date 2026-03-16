from __future__ import annotations

import json

import pytest

from tests.helpers import parse_json_output, run_bash
import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


@pytest.mark.parametrize(
    ("command", "decision"),
    [
        ("git push origin main", "deny"),
        ("git push origin master", "deny"),
        ("git push --force origin feature", "deny"),
        ("git reset --hard HEAD~1", "ask"),
        ("git clean -f", "ask"),
        ("rm -rf /tmp/demo", "ask"),
        ("git status", "allow"),
    ],
)
def test_branch_guard_decisions(repo_root, tmp_path, command: str, decision: str) -> None:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    payload = json.dumps({"tool_input": {"command": command}})

    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    # New Claude Code PreToolUse schema: hookSpecificOutput.permissionDecision
    assert output["hookSpecificOutput"]["permissionDecision"] == decision
