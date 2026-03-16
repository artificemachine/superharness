from __future__ import annotations

import json
import re

from tests.helpers import run_bash
import sys
import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

def test_ledger_append_writes_line(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/hooks/ledger-append.sh"
    ledger = tmp_path / ".superharness/ledger.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# Ledger\n")

    payload = json.dumps({"tool_input": {"file_path": "src/service.py"}})
    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
    text = ledger.read_text()
    assert "modified: service.py" in text
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", text)


def test_ledger_append_skips_superharness_and_ledger(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/hooks/ledger-append.sh"
    ledger = tmp_path / ".superharness/ledger.md"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("# Ledger\n")

    payload1 = json.dumps({"tool_input": {"file_path": ".superharness/contract.yaml"}})
    payload2 = json.dumps({"tool_input": {"file_path": ".superharness/ledger.md"}})

    run_bash(script, cwd=tmp_path, stdin=payload1)
    run_bash(script, cwd=tmp_path, stdin=payload2)

    assert ledger.read_text() == "# Ledger\n"


def test_ledger_append_no_ledger_noop(repo_root, tmp_path) -> None:
    script = repo_root / "adapters/claude-code/hooks/ledger-append.sh"
    payload = json.dumps({"tool_input": {"file_path": "src/service.py"}})

    result = run_bash(script, cwd=tmp_path, stdin=payload)

    assert result.returncode == 0, result.stderr
