from __future__ import annotations

import json

import pytest

from tests.helpers import parse_json_output, run_bash
import sys

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _get_decision(output: dict) -> str:
    """Extract the permission decision from hook output (new format)."""
    return output["hookSpecificOutput"]["permissionDecision"]


@pytest.mark.parametrize(
    ("file_path", "decision"),
    [
        # .env variants
        (".env", "deny"),
        ("config/.env.local", "deny"),
        # credentials
        ("credentials.json", "deny"),
        ("config/credentials.yaml", "deny"),
        # secrets — only specific extensions are blocked
        ("secrets.json", "deny"),
        ("config/app.secrets.yaml", "deny"),
        ("secrets.yml", "deny"),
        ("secrets.toml", "deny"),
        ("secrets.txt", "allow"),           # plain .txt is not blocked
        ("my_notes_secrets.md", "allow"),   # non-secret extension not blocked
        # key / cert files
        ("keys/id_rsa.key", "deny"),
        ("server.pem", "deny"),
        # ssh / kube
        ("/Users/test/.ssh/id_ed25519", "deny"),
        ("/Users/test/.kube/config", "deny"),
        # terraform
        ("infra/terraform.tfvars", "deny"),
        ("prod.tfvars", "deny"),
        ("prod.tfvars.json", "deny"),
        # warn cases
        ("/etc/hosts", "ask"),
        ("/tmp/build.log", "ask"),
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
    assert _get_decision(output) == decision


def test_scope_guard_allows_with_contract(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/hooks/scope-guard.sh"
    contract = tmp_path / ".superharness/contract.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text("id: demo\n")

    payload = json.dumps({"tool_input": {"file_path": "app/service.py"}})
    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    output = parse_json_output(result.stdout)
    assert _get_decision(output) == "allow"
