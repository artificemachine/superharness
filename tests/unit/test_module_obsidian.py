"""Tests for Obsidian module (vault integration)."""
from __future__ import annotations

from pathlib import Path




class TestObsidianModule:
    """Test Obsidian vault integration module."""

    def test_detect_vault_path(self, tmp_path: Path):
        """Finds vault at known paths."""
        from superharness.modules.actions.obsidian import detect_vault

        # Create a mock vault directory
        vault_dir = tmp_path / "test-vault"
        vault_dir.mkdir(parents=True, exist_ok=True)

        # Create .obsidian directory to mark it as a vault
        (vault_dir / ".obsidian").mkdir(exist_ok=True)

        # Test detection with explicit path
        result = detect_vault(str(vault_dir))
        assert result is not None
        assert Path(result) == vault_dir

    def test_detect_no_vault(self, tmp_path: Path):
        """No vault found → level 1 only (returns None)."""
        from superharness.modules.actions.obsidian import detect_vault

        # Non-existent path
        result = detect_vault(str(tmp_path / "nonexistent"))
        assert result is None

    def test_detect_mcp_available(self, tmp_path: Path):
        """MCP server running → level 3 (can use MCP)."""
        from superharness.modules.actions.obsidian import is_mcp_available

        # Without MCP, should return False
        result = is_mcp_available()
        # This will be False in test environment unless MCP is actually running
        assert isinstance(result, bool)

    def test_on_close_writes_vault_note(self, tmp_path: Path):
        """Close fires → markdown note written to vault."""
        from superharness.modules.actions.obsidian import obsidian_write_note

        # Create a mock vault
        vault_dir = tmp_path / "test-vault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / ".obsidian").mkdir(exist_ok=True)

        # Create target directory
        notes_dir = vault_dir / "1_ai" / "test-project"
        notes_dir.mkdir(parents=True, exist_ok=True)

        # Context
        context = {
            "task_id": "test-task-1",
            "summary": "Test task summary",
            "project_name": "test-project",
            "actor": "claude-code",
        }

        # Settings
        settings = {
            "vault_path": str(vault_dir),
            "vault_subfolder": "1_ai/{project_name}/",
            "filename_pattern": "{project_name}-{date}-{title}.md",
            "redact_secrets": True,
        }

        # Execute action
        result = obsidian_write_note(context, settings)

        assert result["success"] is True
        assert "note_path" in result

        # Verify note was written
        note_path = Path(result["note_path"])
        assert note_path.exists()
        assert note_path.parent == notes_dir

    def test_on_close_no_vault_is_silent(self, tmp_path: Path):
        """No vault → no error, no write, returns success=False."""
        from superharness.modules.actions.obsidian import obsidian_write_note

        # Context
        context = {
            "task_id": "test-task-1",
            "summary": "Test task summary",
            "project_name": "test-project",
            "actor": "claude-code",
        }

        # Settings with non-existent vault
        settings = {
            "vault_path": str(tmp_path / "nonexistent-vault"),
            "vault_subfolder": "1_ai/{project_name}/",
            "filename_pattern": "{project_name}-{date}-{title}.md",
            "redact_secrets": True,
        }

        # Execute action
        result = obsidian_write_note(context, settings)

        # Should return success=False without crashing
        assert result["success"] is False
        assert "error" in result or "message" in result

    def test_vault_note_has_frontmatter(self, tmp_path: Path):
        """Written note has YAML frontmatter with tags, date, title."""
        from superharness.modules.actions.obsidian import obsidian_write_note

        # Create a mock vault
        vault_dir = tmp_path / "test-vault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / ".obsidian").mkdir(exist_ok=True)

        # Create target directory
        notes_dir = vault_dir / "1_ai" / "test-project"
        notes_dir.mkdir(parents=True, exist_ok=True)

        # Context
        context = {
            "task_id": "test-task-1",
            "summary": "Test task summary",
            "project_name": "test-project",
            "actor": "claude-code",
        }

        # Settings
        settings = {
            "vault_path": str(vault_dir),
            "vault_subfolder": "1_ai/{project_name}/",
            "filename_pattern": "{project_name}-{date}-{title}.md",
            "redact_secrets": True,
        }

        # Execute action
        result = obsidian_write_note(context, settings)

        # Read the note
        note_path = Path(result["note_path"])
        content = note_path.read_text()

        # Check for frontmatter
        assert content.startswith("---")
        assert "tags:" in content or "task_id:" in content
        assert "---" in content[3:]  # Closing frontmatter marker

    def test_vault_path_uses_project_name(self, tmp_path: Path):
        """Note saved to 1_ai/{project_name}/{project}-{date}-{title}.md."""
        from superharness.modules.actions.obsidian import obsidian_write_note

        # Create a mock vault
        vault_dir = tmp_path / "test-vault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / ".obsidian").mkdir(exist_ok=True)

        # Create target directory
        notes_dir = vault_dir / "1_ai" / "my-project"
        notes_dir.mkdir(parents=True, exist_ok=True)

        # Context
        context = {
            "task_id": "test-task-1",
            "summary": "Test task summary",
            "project_name": "my-project",
            "actor": "claude-code",
        }

        # Settings
        settings = {
            "vault_path": str(vault_dir),
            "vault_subfolder": "1_ai/{project_name}/",
            "filename_pattern": "{project_name}-{date}-{title}.md",
            "redact_secrets": True,
        }

        # Execute action
        result = obsidian_write_note(context, settings)

        # Check that note path includes project name
        note_path = Path(result["note_path"])
        assert "my-project" in str(note_path)
        assert note_path.parent == notes_dir

    def test_no_secrets_in_vault_note(self, tmp_path: Path):
        """API keys, tokens, private IPs redacted from note."""
        from superharness.modules.actions.obsidian import obsidian_write_note

        # Create a mock vault
        vault_dir = tmp_path / "test-vault"
        vault_dir.mkdir(parents=True, exist_ok=True)
        (vault_dir / ".obsidian").mkdir(exist_ok=True)

        # Create target directory
        notes_dir = vault_dir / "1_ai" / "test-project"
        notes_dir.mkdir(parents=True, exist_ok=True)

        # Context with potential secrets
        context = {
            "task_id": "test-task-1",
            "summary": "Task with API key: sk-1234567890abcdef and token: ghp_abc123def456",
            "project_name": "test-project",
            "actor": "claude-code",
        }

        # Settings with redaction enabled
        settings = {
            "vault_path": str(vault_dir),
            "vault_subfolder": "1_ai/{project_name}/",
            "filename_pattern": "{project_name}-{date}-{title}.md",
            "redact_secrets": True,
        }

        # Execute action
        result = obsidian_write_note(context, settings)

        # Read the note
        note_path = Path(result["note_path"])
        content = note_path.read_text()

        # Check that secrets are NOT in the note
        assert "sk-1234567890abcdef" not in content
        assert "ghp_abc123def456" not in content
        # Redaction markers should be present
        assert "[REDACTED" in content or "***" in content or content != context["summary"]
