from __future__ import annotations

import os
import subprocess
import sys
import yaml
from pathlib import Path

from tests.helpers import REPO_ROOT, copy_from_repo, run_bash, shell_guard_list
import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="requires bash")


def _run_enqueue(args: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.inbox_enqueue"] + args,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_claude_watcher_dispatch_smoke(repo_root: Path, tmp_path: Path) -> None:
    """
    Smoke test: verify claude-code watcher dispatch end-to-end.

    Flow:
    1. Initialize project with contract + inbox
    2. Enqueue a task for claude-code
    3. Run inbox-dispatch in non-interactive mode with a mock claude
    4. Verify inbox item transitions launched -> done
    5. Verify contract task status updates to done
    """
    project = tmp_path / "project"
    project.mkdir()

    # Bootstrap project
    init_env = os.environ.copy()
    init_env["PYTHONPATH"] = str(REPO_ROOT / "src")
    init_res = subprocess.run(
        [sys.executable, "-m", "superharness.commands.init_project", "WatcherTest", "Shell", "active"],
        cwd=str(project), text=True, capture_output=True, env=init_env, check=False
    )
    assert init_res.returncode == 0, f"init failed: {init_res.stderr}"

    # Copy required scripts
    required = (
        shell_guard_list(REPO_ROOT, "--list-entrypoints")
        + shell_guard_list(REPO_ROOT, "--list-hooks")
        + [
            "protocol/templates/identity-core.md",
            "superharness",
        ]
    )
    for rel in sorted(set(required)):
        copy_from_repo(rel, project)

    # Create a simple test task in contract using YAML manipulation
    contract_file = project / ".superharness/contract.yaml"
    with open(contract_file) as f:
        contract_doc = yaml.safe_load(f)

    # Add a test task
    if "tasks" not in contract_doc:
        contract_doc["tasks"] = []

    contract_doc["tasks"].append({
        "id": "smoke-test-task",
        "title": "Smoke test task for watcher",
        "status": "todo",
        # `workflow: quick` bypasses the implementation plan-phase gate so the
        # smoke test can enqueue a todo task directly (implementation workflow
        # requires plan_approved; quick accepts todo per engine.lifecycle).
        "workflow": "quick",
        "owner": "claude-code",
        "project_path": str(project),
    })

    with open(contract_file, "w") as f:
        yaml.dump(contract_doc, f, default_flow_style=False, sort_keys=False)

    # Enqueue the task
    enqueue_res = _run_enqueue([
        "--project", str(project),
        "--to", "claude-code",
        "--task", "smoke-test-task",
        "--priority", "1",
    ])
    assert enqueue_res.returncode == 0, f"enqueue failed: {enqueue_res.stderr}"
    assert "Enqueued inbox item" in enqueue_res.stdout

    # Create mock delegate-to-claude.sh that marks task done without launching Claude
    mock_scripts_dir = project / "scripts"
    mock_scripts_dir.mkdir(parents=True, exist_ok=True)
    mock_launcher = mock_scripts_dir / "delegate-to-claude.sh"
    mock_launcher.write_text("""#!/bin/bash
set -euo pipefail
PYTHON3="${SUPERHARNESS_PYTHON:-python3}"

PROJECT_DIR=""
TASK_ID=""
PRINT_ONLY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --project)
      PROJECT_DIR="$2"
      shift 2
      ;;
    --task)
      TASK_ID="$2"
      shift 2
      ;;
    --print-only)
      PRINT_ONLY=1
      shift
      ;;
    *)
      shift
      ;;
  esac
done

if [ "$PRINT_ONLY" -eq 1 ]; then
  exit 0
fi

"$PYTHON3" - "$PROJECT_DIR" "$TASK_ID" <<'PY'
import sys
import yaml
from datetime import datetime, timezone

project_dir = sys.argv[1]
task_id = sys.argv[2]

contract_file = f"{project_dir}/.superharness/contract.yaml"
with open(contract_file) as f:
    doc = yaml.safe_load(f) or {}
for task in (doc.get("tasks") or []):
    if str(task.get("id", "")) == str(task_id):
        task["status"] = "done"
        break
with open(contract_file, "w") as f:
    yaml.dump(doc, f, default_flow_style=False, sort_keys=False)

ledger_file = f"{project_dir}/.superharness/ledger.md"
today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
with open(ledger_file, "a") as f:
    f.write(f"{today} | {task_id} | claude-code | Mock smoke test execution\\n")
PY
""")
    mock_launcher.chmod(0o755)

    # Run inbox-dispatch in non-interactive mode
    dispatch_script = REPO_ROOT / "src/superharness/scripts/inbox-dispatch.sh"
    dispatch_env = {
        "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": "YES",
        "SUPERHARNESS_SCRIPTS_DIR": str(mock_scripts_dir),
        # Unset to allow claude to launch in nested test environments
        "CLAUDECODE": None,
    }
    dispatch_res = run_bash(
        dispatch_script,
        cwd=project,
        env=dispatch_env,
        args=[
            "--project", str(project),
            "--to", "claude-code",
            "--non-interactive",
        ],
    )

    # Verify dispatch succeeded (may exit 0 even if task execution fails in reconcile)
    assert dispatch_res.returncode == 0, f"dispatch failed: {dispatch_res.stderr}\nstdout: {dispatch_res.stdout}"
    assert "Inbox item updated" in dispatch_res.stdout, "No inbox update in output: " + dispatch_res.stdout

    # Verify contract task status is done (read YAML directly)
    with open(contract_file) as f:
        contract_result = yaml.safe_load(f)

    task_found = False
    for task in contract_result.get("tasks", []):
        if task.get("id") == "smoke-test-task":
            task_found = True
            assert task.get("status") == "done", f"Expected task status 'done', got: {task.get('status')}"
            break

    assert task_found, "smoke-test-task not found in contract"

    # Verify ledger was updated
    ledger_file = project / ".superharness/ledger.md"
    assert ledger_file.exists(), "Ledger file not created"
    ledger_content = ledger_file.read_text()
    assert "smoke-test-task" in ledger_content, "Task not found in ledger"
    assert "claude-code" in ledger_content, "Owner not found in ledger"

    # Verify inbox item transitioned to done
    inbox_file = project / ".superharness/inbox.yaml"
    with open(inbox_file) as f:
        inbox_items = yaml.safe_load(f)

    # inbox.yaml is a list of items
    inbox_item_found = False
    if isinstance(inbox_items, list):
        for item in inbox_items:
            if item.get("task") == "smoke-test-task":
                inbox_item_found = True
                assert item.get("status") == "done", f"Inbox item not marked done: {item.get('status')}"
                break

    assert inbox_item_found, "Inbox item not found for smoke-test-task"
