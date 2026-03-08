from __future__ import annotations

import json

import pytest

from tests.helpers import parse_json_output, run_bash


@pytest.mark.parametrize(
    ("command", "decision"),
    [
        ("git push origin main", "block"),
        ("git push origin master", "block"),
        ("git push --force origin feature", "block"),
        ("git reset --hard HEAD~1", "warn"),
        ("git clean -f", "warn"),
        ("rm -rf /tmp/demo", "warn"),
        ("git status", "allow"),
    ],
)
def test_branch_guard_decisions(repo_root, tmp_path, command: str, decision: str) -> None:
    script = repo_root / "adapters/claude-code/hooks/branch-guard.sh"
    payload = json.dumps({"tool_input": {"command": command}})

    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    assert output["decision"] == decision
