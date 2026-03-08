from __future__ import annotations

import json

import pytest

from tests.helpers import parse_json_output, run_bash


@pytest.mark.parametrize(
    ("file_path", "decision"),
    [
        (".env", "block"),
        ("config/.env.local", "block"),
        ("secrets.txt", "block"),
        ("keys/id_rsa.key", "block"),
        ("/etc/hosts", "warn"),
        ("/tmp/build.log", "warn"),
        ("src/main.py", "allow"),
    ],
)
def test_scope_guard_policies(repo_root, tmp_path, file_path: str, decision: str) -> None:
    script = repo_root / "adapters/claude-code/hooks/scope-guard.sh"
    payload = json.dumps({"tool_input": {"file_path": file_path}})

    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    assert output["decision"] == decision


def test_scope_guard_allows_with_contract(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/hooks/scope-guard.sh"
    contract = tmp_path / ".superreins/contract.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("id: demo\n")

    payload = json.dumps({"tool_input": {"file_path": "app/service.py"}})
    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    assert output["decision"] == "allow"
