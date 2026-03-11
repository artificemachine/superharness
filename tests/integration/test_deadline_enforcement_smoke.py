"""
Integration smoke test: verify inbox-deadline-check sets contract failed+reason on expiry.

This test validates the complete deadline enforcement flow:
1. Create a contract task with deadline_minutes set
2. Create a launched inbox item with timestamp in the past (to simulate expiry)
3. Run inbox-deadline-check.sh
4. Verify:
   - Inbox item marked as failed with deadline_exceeded reason
   - Contract task marked as failed with stopped_reason containing deadline_exceeded_after_Xm
   - Handoff created documenting the deadline enforcement
   - New inbox item created for the alternate owner
   - Ledger entry added documenting the deadline enforcement
"""

from __future__ import annotations

from tests.helpers import run_bash


def _create_test_project(tmp_path, task_id: str, owner: str, deadline_minutes: int, launched_at: str):
    """Helper to create a realistic test project with contract + inbox."""
    project = tmp_path / "deadline-smoke-project"
    project.mkdir()
    harness = project / ".superharness"
    harness.mkdir(parents=True, exist_ok=True)
    (harness / "handoffs").mkdir()
    (harness / "failures.yaml").write_text("failures: []\n")
    (harness / "decisions.yaml").write_text("decisions: []\n")

    # Create contract with deadline_minutes.
    (harness / "contract.yaml").write_text(
        f"id: smoke-contract\n"
        f"created: 2026-03-10\n"
        f"created_by: owner\n"
        f"status: active\n"
        f"goal: Smoke test deadline enforcement\n"
        f"tasks:\n"
        f"  - id: {task_id}\n"
        f"    title: Task that will exceed deadline\n"
        f"    status: in_progress\n"
        f"    owner: {owner}\n"
        f"    deadline_minutes: {deadline_minutes}\n"
        f'    project_path: "{project}"\n'
        f"decisions: []\n"
        f"failures: []\n"
    )

    # Create inbox with launched item (timestamp in the past to trigger expiry).
    (harness / "inbox.yaml").write_text(
        f"# Delegation inbox\n"
        f"---\n"
        f"- id: inbox-{task_id}\n"
        f"  to: {owner}\n"
        f"  task: {task_id}\n"
        f'  project: "{project}"\n'
        f"  status: launched\n"
        f"  launched_at: {launched_at}\n"
        f"  priority: 2\n"
        f"  retry_count: 1\n"
        f"  max_retries: 3\n"
    )

    (harness / "ledger.md").write_text("# Ledger\n\nAppend-only activity log.\n")

    return project


def test_deadline_enforcement_full_integration(repo_root, tmp_path) -> None:
    """
    Smoke test: verify inbox-deadline-check sets contract failed+reason on expiry.

    This is the acceptance test for task deadline-enforcement-smoke.
    """
    task_id = "will-expire-task"
    owner = "claude-code"
    deadline_minutes = 5
    launched_at = "2026-01-01T00:00:00Z"  # Far in the past (> 5 minutes ago)

    project = _create_test_project(tmp_path, task_id, owner, deadline_minutes, launched_at)

    # Run inbox-deadline-check.
    script = repo_root / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    # Should exit cleanly with exceeded=1.
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert "exceeded=1" in result.stdout, f"Expected exceeded=1, got: {result.stdout}"

    # 1. Verify inbox item is marked as failed.
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: failed" in inbox_text, "Original inbox item should be marked failed"
    assert "deadline_exceeded" in inbox_text, "Should have deadline_exceeded reason"

    # 2. Verify contract task is marked as failed with stopped_reason.
    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: failed" in contract_text, "Contract task should be marked failed"
    assert "stopped_reason: deadline_exceeded_after_" in contract_text, \
        "Contract task should have stopped_reason with deadline_exceeded_after_Xm"
    assert "stopped_at:" in contract_text, "Contract task should have stopped_at timestamp"

    # 3. Verify handoff was created.
    handoff_files = list((project / ".superharness" / "handoffs").glob(f"*deadline-{task_id}.yaml"))
    assert len(handoff_files) == 1, f"Expected 1 handoff, found {len(handoff_files)}"
    handoff_text = handoff_files[0].read_text()
    assert "status: deadline_exceeded" in handoff_text, "Handoff should have deadline_exceeded status"
    assert f"from: {owner}" in handoff_text, f"Handoff should indicate original owner {owner}"
    assert "to: codex-cli" in handoff_text, "Handoff should reassign to codex-cli"
    assert f"deadline_minutes: {deadline_minutes}" in handoff_text, "Handoff should document deadline"

    # 4. Verify new inbox item created for alternate owner.
    assert "to: codex-cli" in inbox_text, "Should have re-enqueued item for codex-cli"
    assert inbox_text.count("status: pending") >= 1, "New item should be pending"

    # 5. Verify ledger entry added.
    ledger_text = (project / ".superharness" / "ledger.md").read_text()
    assert "deadline-exceeded" in ledger_text, "Ledger should have deadline-exceeded entry"
    assert task_id in ledger_text, "Ledger should reference the task"
    assert "codex-cli" in ledger_text, "Ledger should reference the new owner"


def test_deadline_not_yet_exceeded_no_action(repo_root, tmp_path) -> None:
    """
    Negative test: verify no action when deadline hasn't been exceeded yet.
    """
    from datetime import datetime, timezone

    task_id = "fresh-task"
    owner = "codex-cli"
    deadline_minutes = 60
    launched_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # Just now

    project = _create_test_project(tmp_path, task_id, owner, deadline_minutes, launched_at)

    script = repo_root / "scripts" / "inbox-deadline-check.sh"
    result = run_bash(script, cwd=repo_root, args=["--project", str(project)])

    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert "exceeded=0" in result.stdout, "Should report 0 exceeded tasks"

    # Verify no changes to inbox, contract, or ledger.
    inbox_text = (project / ".superharness" / "inbox.yaml").read_text()
    assert "status: launched" in inbox_text, "Inbox item should remain launched"
    assert inbox_text.count("status: pending") == 0, "No new item should be created"

    contract_text = (project / ".superharness" / "contract.yaml").read_text()
    assert "status: in_progress" in contract_text, "Contract task should remain in_progress"
    assert "stopped_reason" not in contract_text, "No stopped_reason should be added"

    handoff_files = list((project / ".superharness" / "handoffs").glob("*.yaml"))
    assert len(handoff_files) == 0, "No handoff should be created"
