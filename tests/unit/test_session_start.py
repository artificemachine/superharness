from __future__ import annotations

import json
import re
from pathlib import Path

from tests.helpers import run_bash
import sys
import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")

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


def test_session_start_vault_search_uses_stdin_not_argv(repo_root: Path) -> None:
    """Regression: SEARCH_RESULT must be passed via stdin, not sys.argv[1].

    Passing large/special-char JSON as a CLI arg causes SHELL-002 (word splitting /
    CWE-78). The fix pipes $SEARCH_RESULT through stdin so $VAR is never exposed as
    an unquoted shell argument.
    """
    script = repo_root / "adapters/claude-code/hooks/session-start.sh"
    src = script.read_text()

    # Must NOT pass $SEARCH_RESULT as a bare shell argument to python3 -c
    # (old pattern: closing-quote + "$SEARCH_RESULT" on same line)
    assert not re.search(r'"\s*"\$SEARCH_RESULT"', src), (
        "session-start.sh must not pass $SEARCH_RESULT as sys.argv; "
        "use stdin (echo \"$SEARCH_RESULT\" | python3 ...) instead."
    )
    # Must use stdin instead
    assert "sys.stdin.read()" in src, (
        "session-start.sh must read SEARCH_RESULT from sys.stdin.read()"
    )
