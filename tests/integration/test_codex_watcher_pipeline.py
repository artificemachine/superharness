from __future__ import annotations

import yaml
from pathlib import Path

from tests.helpers import REPO_ROOT, copy_from_repo, run_bash, shell_guard_list


def test_codex_watcher_dispatch_smoke(repo_root: Path, tmp_path: Path) -> None:
    """
    Smoke test: verify codex-cli watcher dispatch end-to-end.

    Flow:
    1. Initialize project with contract + inbox
    2. Enqueue a task for codex-cli
    3. Run inbox-dispatch in non-interactive mode with a mock codex launcher
    4. Verify inbox item transitions launched -> done
    5. Verify contract task status updates to done
    """
    project = tmp_path / "project"
    project.mkdir()

    init_script = repo_root / "init-project.sh"
    init_res = run_bash(init_script, cwd=project, args=["WatcherTest", "Shell", "active"])
    assert init_res.returncode == 0, f"init failed: {init_res.stderr}"

    required = (
        shell_guard_list(REPO_ROOT, "--list-entrypoints")
        + shell_guard_list(REPO_ROOT, "--list-hooks")
        + [
            "protocol/templates/identity-core.md",
            "scripts/inbox-yaml.rb",
            "cli/contract-today.sh",
            "cli/doctor.sh",
            "cli/install-wrapper.sh",
            "cli/delegate-task.sh",
            "cli/task.sh",
            "engine/contract.rb",
            "engine/inbox.rb",
            "superharness",
        ]
    )
    for rel in sorted(set(required)):
        copy_from_repo(rel, project)

    contract_file = project / ".superharness/contract.yaml"
    with open(contract_file) as f:
        contract_doc = yaml.safe_load(f)

    if "tasks" not in contract_doc:
        contract_doc["tasks"] = []

    contract_doc["tasks"].append(
        {
            "id": "smoke-test-task",
            "title": "Smoke test task for watcher",
            "status": "todo",
            "owner": "codex-cli",
            "project_path": str(project),
        }
    )

    with open(contract_file, "w") as f:
        yaml.dump(contract_doc, f, default_flow_style=False, sort_keys=False)

    enqueue_script = project / "scripts/inbox-enqueue.sh"
    enqueue_res = run_bash(
        enqueue_script,
        cwd=project,
        args=[
            "--project",
            str(project),
            "--to",
            "codex-cli",
            "--task",
            "smoke-test-task",
            "--priority",
            "1",
        ],
    )
    assert enqueue_res.returncode == 0, f"enqueue failed: {enqueue_res.stderr}"
    assert "Enqueued inbox item" in enqueue_res.stdout

    mock_launcher = project / "scripts/delegate-to-codex.sh"
    mock_launcher.write_text(
        """#!/bin/bash
set -euo pipefail

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

python3 - "$PROJECT_DIR" "$TASK_ID" <<'PY'
import sys
from datetime import datetime
from pathlib import Path
import yaml

project_dir = Path(sys.argv[1])
task_id = sys.argv[2]

contract_file = project_dir / ".superharness/contract.yaml"
with open(contract_file) as f:
    contract_doc = yaml.safe_load(f)

for task in contract_doc.get("tasks", []):
    if task.get("id") == task_id:
        task["status"] = "done"
        break

with open(contract_file, "w") as f:
    yaml.dump(contract_doc, f, default_flow_style=False, sort_keys=False)

ledger_file = project_dir / ".superharness/ledger.md"
today = datetime.utcnow().strftime("%Y-%m-%d")
with open(ledger_file, "a") as f:
    f.write(f"{today} | {task_id} | codex-cli | Mock smoke test execution\\n")
PY
"""
    )
    mock_launcher.chmod(0o755)

    dispatch_script = project / "scripts/inbox-dispatch.sh"
    dispatch_env = {
        "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
    }
    dispatch_res = run_bash(
        dispatch_script,
        cwd=project,
        env=dispatch_env,
        args=[
            "--project",
            str(project),
            "--to",
            "codex-cli",
            "--non-interactive",
        ],
    )

    assert dispatch_res.returncode == 0, f"dispatch failed: {dispatch_res.stderr}\nstdout: {dispatch_res.stdout}"
    assert "Inbox item updated" in dispatch_res.stdout, f"No inbox update in output: {dispatch_res.stdout}"

    with open(contract_file) as f:
        contract_result = yaml.safe_load(f)

    task_found = False
    for task in contract_result.get("tasks", []):
        if task.get("id") == "smoke-test-task":
            task_found = True
            assert task.get("status") == "done", f"Expected task status 'done', got: {task.get('status')}"
            break

    assert task_found, "smoke-test-task not found in contract"

    ledger_file = project / ".superharness/ledger.md"
    assert ledger_file.exists(), "Ledger file not created"
    ledger_content = ledger_file.read_text()
    assert "smoke-test-task" in ledger_content, "Task not found in ledger"
    assert "codex-cli" in ledger_content, "Owner not found in ledger"

    inbox_file = project / ".superharness/inbox.yaml"
    with open(inbox_file) as f:
        inbox_items = yaml.safe_load(f)

    inbox_item_found = False
    if isinstance(inbox_items, list):
        for item in inbox_items:
            if item.get("task") == "smoke-test-task":
                inbox_item_found = True
                assert item.get("status") == "done", f"Inbox item not marked done: {item.get('status')}"
                break

    assert inbox_item_found, "Inbox item not found for smoke-test-task"
