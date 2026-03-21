"""Tests for Remember module (context refresh)."""
from __future__ import annotations

from pathlib import Path

import pytest


class TestRememberModule:
    """Test Remember module for context refresh on continue."""

    def test_on_continue_refreshes_context(self, tmp_path: Path):
        """Continue fires → reads CLAUDE.md, last handoff, contract."""
        from superharness.modules.actions.remember import refresh_context

        # Setup project structure
        project_dir = tmp_path / "test-project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create CLAUDE.md
        claude_md = project_dir / "CLAUDE.md"
        claude_md.write_text("# Test Project\n\nThis is a test project.", encoding="utf-8")

        # Create .superharness structure
        sh_dir = project_dir / ".superharness"
        sh_dir.mkdir(parents=True, exist_ok=True)

        # Create contract
        contract = sh_dir / "contract.yaml"
        contract.write_text(
            """id: test-contract
goal: Test contract goal
tasks:
  - id: test-task
    title: Test task
    status: todo
""",
            encoding="utf-8",
        )

        # Create handoff
        handoffs_dir = sh_dir / "handoffs"
        handoffs_dir.mkdir(parents=True, exist_ok=True)
        handoff = handoffs_dir / "001-test-task-claude-code.md"
        handoff.write_text(
            """# Handoff: test-task

Task summary and outcomes here.
""",
            encoding="utf-8",
        )

        # Context
        context = {
            "task_id": "test-task",
            "project_dir": str(project_dir),
            "actor": "claude-code",
        }

        # Settings (empty for remember module)
        settings = {}

        # Execute action
        result = refresh_context(context, settings)

        assert result["success"] is True
        assert "context_refreshed" in result
        assert result["context_refreshed"]["claude_md"] is True
        assert result["context_refreshed"]["contract"] is True
        assert result["context_refreshed"]["last_handoff"] is True

    def test_on_continue_no_handoff_still_works(self, tmp_path: Path):
        """No previous handoff → just reads CLAUDE.md and contract."""
        from superharness.modules.actions.remember import refresh_context

        # Setup project structure
        project_dir = tmp_path / "test-project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Create CLAUDE.md
        claude_md = project_dir / "CLAUDE.md"
        claude_md.write_text("# Test Project\n\nThis is a test project.", encoding="utf-8")

        # Create .superharness structure (but no handoffs)
        sh_dir = project_dir / ".superharness"
        sh_dir.mkdir(parents=True, exist_ok=True)

        # Create contract
        contract = sh_dir / "contract.yaml"
        contract.write_text(
            """id: test-contract
goal: Test contract goal
tasks: []
""",
            encoding="utf-8",
        )

        # Context (no handoffs directory)
        context = {
            "task_id": "test-task",
            "project_dir": str(project_dir),
            "actor": "claude-code",
        }

        # Settings
        settings = {}

        # Execute action
        result = refresh_context(context, settings)

        assert result["success"] is True
        assert result["context_refreshed"]["claude_md"] is True
        assert result["context_refreshed"]["contract"] is True
        # No handoff exists, so it should be False or not error
        assert result["context_refreshed"]["last_handoff"] is False
