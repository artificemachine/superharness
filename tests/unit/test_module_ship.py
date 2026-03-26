"""Tests for ship module (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

import subprocess



class TestShipModule:
    """Test ship module (auto-commit on close)."""

    def test_on_close_runs_ship(self, tmp_path):
        """Close fires → git add, commit, push."""
        from superharness.modules.actions.ship import git_ship

        project = tmp_path / "proj"
        project.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        # Disable hooks for testing
        subprocess.run(
            ["git", "config", "core.hooksPath", "/dev/null"],
            cwd=project,
            check=True,
            capture_output=True,
        )

        # Create a file with uncommitted changes
        test_file = project / "test.txt"
        test_file.write_text("test content")

        context = {
            "task_id": "test.1",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Completed task test.1",
        }

        settings = {
            "auto_push": False,  # Don't push in tests
        }

        result = git_ship(context, settings)

        # Verify success
        assert result["success"] is True
        assert "committed" in result.get("message", "").lower()

        # Verify file was committed
        status_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project,
            capture_output=True,
            text=True,
        )
        assert status_result.stdout.strip() == "", "Working directory should be clean"

    def test_on_close_no_changes_skips(self, tmp_path):
        """No uncommitted changes → ship skipped."""
        from superharness.modules.actions.ship import git_ship

        project = tmp_path / "proj"
        project.mkdir()

        # Initialize git repo
        subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=project,
            check=True,
            capture_output=True,
        )
        # Disable hooks for testing
        subprocess.run(
            ["git", "config", "core.hooksPath", "/dev/null"],
            cwd=project,
            check=True,
            capture_output=True,
        )

        # Create initial commit (no pending changes)
        test_file = project / "test.txt"
        test_file.write_text("test content")
        subprocess.run(["git", "add", "."], cwd=project, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"],
            cwd=project,
            check=True,
            capture_output=True,
        )

        context = {
            "task_id": "test.2",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Completed task test.2",
        }

        settings = {
            "auto_push": False,
        }

        result = git_ship(context, settings)

        # Should skip gracefully
        assert result["success"] is True
        assert "skipped" in result.get("message", "").lower() or "nothing to commit" in result.get("message", "").lower()

    def test_on_close_ship_failure_warns(self, tmp_path):
        """Ship fails → warning, close still succeeds."""
        from superharness.modules.actions.ship import git_ship

        project = tmp_path / "proj"
        project.mkdir()

        # No git repo → commit will fail

        context = {
            "task_id": "test.3",
            "project_dir": str(project),
            "event": "on_close",
            "summary": "Completed task test.3",
        }

        settings = {
            "auto_push": False,
        }

        result = git_ship(context, settings)

        # Should fail gracefully without crashing
        assert result["success"] is False
        assert "error" in result or "message" in result
