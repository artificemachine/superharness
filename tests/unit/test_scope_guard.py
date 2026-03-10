from __future__ import annotations

import json

import pytest

from tests.helpers import parse_json_output, run_bash


@pytest.mark.parametrize(
    ("file_path", "decision"),
    [
        # .env variants
        (".env", "block"),
        ("config/.env.local", "block"),
        # credentials
        ("credentials.json", "block"),
        ("config/credentials.yaml", "block"),
        # secrets — only specific extensions are blocked
        ("secrets.json", "block"),
        ("config/app.secrets.yaml", "block"),
        ("secrets.yml", "block"),
        ("secrets.toml", "block"),
        ("secrets.txt", "allow"),           # plain .txt is not blocked
        ("my_notes_secrets.md", "allow"),   # non-secret extension not blocked
        # key / cert files
        ("keys/id_rsa.key", "block"),
        ("server.pem", "block"),
        # ssh / kube
        ("/Users/test/.ssh/id_ed25519", "block"),
        ("/Users/test/.kube/config", "block"),
        # terraform
        ("infra/terraform.tfvars", "block"),
        ("prod.tfvars", "block"),
        ("prod.tfvars.json", "block"),
        # warn cases
        ("/etc/hosts", "warn"),
        ("/tmp/build.log", "warn"),
        # allow
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
    contract = tmp_path / ".superharness/contract.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("id: demo\n")

    payload = json.dumps({"tool_input": {"file_path": "app/service.py"}})
    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    assert output["decision"] == "allow"
