from __future__ import annotations

import json
import yaml
from pathlib import Path

from tests.helpers import REPO_ROOT, copy_from_repo, run_bash, run_cmd, shell_guard_list


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
    init_script = repo_root / "init-project.sh"
    init_res = run_bash(init_script, cwd=project, args=["WatcherTest", "Shell", "active"])
    assert init_res.returncode == 0, f"init failed: {init_res.stderr}"

    # Copy required scripts
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
        "owner": "claude-code",
        "project_path": str(project),
    })

    with open(contract_file, "w") as f:
        yaml.dump(contract_doc, f, default_flow_style=False, sort_keys=False)

    # Enqueue the task
    enqueue_script = repo_root / "scripts/inbox-enqueue.sh"
    enqueue_res = run_bash(
        enqueue_script,
        cwd=project,
        args=[
            "--project", str(project),
            "--to", "claude-code",
            "--task", "smoke-test-task",
            "--priority", "1",
        ],
    )
    assert enqueue_res.returncode == 0, f"enqueue failed: {enqueue_res.stderr}"
    assert "Enqueued inbox item" in enqueue_res.stdout

    # Create mock delegate-to-claude.sh that marks task done without launching Claude
    mock_launcher = project / "scripts/delegate-to-claude.sh"
    mock_launcher.write_text("""#!/usr/bin/env python3
import sys
import yaml
from pathlib import Path
from datetime import datetime

# Mock launcher: parse args and mark task done without launching claude
project_dir = None
task_id = None
print_only = False

i = 1
while i < len(sys.argv):
    if sys.argv[i] == "--project":
        project_dir = sys.argv[i+1]
        i += 2
    elif sys.argv[i] == "--task":
        task_id = sys.argv[i+1]
        i += 2
    elif sys.argv[i] == "--print-only":
        print_only = True
        i += 1
    else:
        i += 1

if print_only:
    sys.exit(0)

# Mock: mark contract task as done
contract_file = Path(project_dir) / ".superharness/contract.yaml"
with open(contract_file) as f:
    contract_doc = yaml.safe_load(f)

for task in contract_doc.get("tasks", []):
    if task.get("id") == task_id:
        task["status"] = "done"
        break

with open(contract_file, "w") as f:
    yaml.dump(contract_doc, f, default_flow_style=False, sort_keys=False)

# Mock: append ledger
ledger_file = Path(project_dir) / ".superharness/ledger.md"
today = datetime.utcnow().strftime("%Y-%m-%d")
with open(ledger_file, "a") as f:
    f.write(f"{today} | {task_id} | claude-code | Mock smoke test execution\\n")

sys.exit(0)
""")
    mock_launcher.chmod(0o755)

    # Run inbox-dispatch in non-interactive mode
    dispatch_script = repo_root / "scripts/inbox-dispatch.sh"
    dispatch_env = {
        "SUPERHARNESS_CONFIRM_NON_INTERACTIVE": "YES",
        "SUPERHARNESS_CONFIRM_SKIP_PERMISSIONS": "YES",
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
    assert "Inbox item updated" in dispatch_res.stdout, f"No inbox update in output: {dispatch_res.stdout}"

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

    assert inbox_item_found, f"Inbox item not found for smoke-test-task"
