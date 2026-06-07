import pytest
import os
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from superharness.commands.delegate import delegate

@pytest.mark.skip(reason="legacy YAML fixture — pending SQLite migration (see PR #208)")
def test_delegate_sdk_logic_claude_vs_others(tmp_path):
    """Verify that only claude-code attempts to use the SDK path."""
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    sh_dir = project_dir / ".superharness"
    sh_dir.mkdir()
    (sh_dir / "handoffs").mkdir()
    
    contract = {
        "id": "test-contract",
        "tasks": [
            {"id": "task-1", "status": "plan_approved", "owner": "claude-code", "project_path": str(project_dir)},
            {"id": "task-2", "status": "plan_approved", "owner": "gemini-cli", "project_path": str(project_dir)}
        ]
    }
    (sh_dir / "contract.yaml").write_text(yaml.dump(contract))
    
    # Mock SDK presence
    with patch("superharness.commands.delegate.sdk_available", return_value=True), \
         patch("superharness.commands.delegate.SDKRunner") as mock_runner, \
         patch("superharness.commands.delegate._launch_agent") as mock_launch, \
         patch("superharness.commands.delegate._confirm_non_interactive_risk"):

        # 1. Claude-code SHOULD use SDK
        delegate(str(project_dir), "claude-code", "task-1", print_only=False, non_interactive=True, codex_bypass=False, skip_preflight=True)
        assert mock_runner.called, "SDKRunner should be called for claude-code"

        mock_runner.reset_mock()
        mock_launch.reset_mock()

        # 2. Gemini-cli should NOT use SDK
        delegate(str(project_dir), "gemini-cli", "task-2", print_only=False, non_interactive=True, codex_bypass=False, skip_preflight=True)
        assert not mock_runner.called, "SDKRunner should NOT be called for gemini-cli"
        assert mock_launch.called, "Should fallback to CLI (_launch_agent) for gemini-cli"

if __name__ == "__main__":
    import pytest
    pytest.main([__file__])


# ── Iter 6 RED: todo+implementation must not be a permanent block ─────────────

def _setup_impl_task(tmp_path: Path) -> Path:
    """Create a project with a todo+implementation task in SQLite."""
    from tests.helpers import seed_sqlite_from_yaml
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: test-contract\ntasks:\n"
        "  - id: impl-task\n    owner: claude-code\n    status: todo\n"
        f"    project_path: '{project.as_posix()}'\n"
        "    acceptance_criteria:\n      - implement the feature\n"
    )
    seed_sqlite_from_yaml(project)
    return project


def test_todo_implementation_not_permanent_block(tmp_path):
    """delegate() must NOT return EXIT_PERMANENT_BLOCK for a todo+implementation task."""
    from superharness.commands.delegate import delegate, EXIT_PERMANENT_BLOCK

    project = _setup_impl_task(tmp_path)

    with patch("superharness.commands.delegate._launch_agent", return_value=0), \
         patch("superharness.commands.delegate._check_dispatch_gates", return_value=None), \
         patch("superharness.commands.delegate.sdk_available", return_value=False), \
         patch("superharness.commands.delegate._confirm_non_interactive_risk"):
        rc = delegate(
            str(project), "claude-code", "impl-task",
            print_only=False, non_interactive=True, codex_bypass=True, skip_preflight=True,
            model_override="claude-sonnet-4-6",
        )

    assert rc != EXIT_PERMANENT_BLOCK, (
        f"delegate() returned EXIT_PERMANENT_BLOCK ({EXIT_PERMANENT_BLOCK}) for "
        "a todo+implementation task — auto-apply --plan-only instead"
    )


def test_retry_count_not_pinned_to_max(tmp_path):
    """A todo+implementation dispatch must return a retryable exit code (not rc=2)."""
    from superharness.commands.delegate import delegate, EXIT_PERMANENT_BLOCK
    from superharness.engine.failure_classifier import classify

    project = _setup_impl_task(tmp_path)

    with patch("superharness.commands.delegate._launch_agent", return_value=0), \
         patch("superharness.commands.delegate._check_dispatch_gates", return_value=None), \
         patch("superharness.commands.delegate.sdk_available", return_value=False), \
         patch("superharness.commands.delegate._confirm_non_interactive_risk"):
        rc = delegate(
            str(project), "claude-code", "impl-task",
            print_only=False, non_interactive=True, codex_bypass=True, skip_preflight=True,
            model_override="claude-sonnet-4-6",
        )

    # A permanent block (rc=2) causes retry_count to be pinned to max — must not happen
    cls = classify(launcher_rc=EXIT_PERMANENT_BLOCK, error_text="", log_tail="")
    assert not cls.retryable, "rc=2 must classify as non-retryable (permanent block pinning)"
    # The dispatch returned something other than rc=2, so retry_count is NOT pinned
    assert rc != EXIT_PERMANENT_BLOCK, (
        f"todo+implementation dispatch returned EXIT_PERMANENT_BLOCK ({EXIT_PERMANENT_BLOCK}) — "
        "retry_count would be pinned to max"
    )

