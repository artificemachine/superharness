"""Tests for module runner (TDD — RED → GREEN → REFACTOR)."""
from __future__ import annotations

from unittest.mock import Mock, patch



class TestModuleRunner:
    """Test module lifecycle hook execution."""

    def test_on_close_fires_for_enabled_module(self, tmp_path):
        """Module with on_close hook → action called when close runs."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "test.yaml").write_text(
            """name: test
enabled: true
hooks:
  on_close:
    action: test_action
settings: {}
detect: {}
"""
        )

        # Mock the action registry
        mock_action = Mock(return_value={"success": True})
        with patch("superharness.modules.runner._ACTION_REGISTRY", {"test_action": mock_action}):
            results = run_hooks("on_close", {"task_id": "t1"}, project)

        assert len(results) == 1
        assert results[0]["module"] == "test"
        assert results[0]["success"] is True
        mock_action.assert_called_once()

    def test_on_close_skips_disabled_module(self, tmp_path):
        """Disabled module → on_close not called."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "disabled.yaml").write_text(
            """name: disabled
enabled: false
hooks:
  on_close:
    action: test_action
settings: {}
detect: {}
"""
        )

        mock_action = Mock()
        with patch("superharness.modules.runner._ACTION_REGISTRY", {"test_action": mock_action}):
            results = run_hooks("on_close", {}, project)

        assert len(results) == 0
        mock_action.assert_not_called()

    def test_on_verify_fires(self, tmp_path):
        """Module with on_verify hook → action called when verify runs."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "verify.yaml").write_text(
            """name: verify
enabled: true
hooks:
  on_verify:
    action: verify_action
settings: {}
detect: {}
"""
        )

        mock_action = Mock(return_value={"verified": True})
        with patch("superharness.modules.runner._ACTION_REGISTRY", {"verify_action": mock_action}):
            results = run_hooks("on_verify", {"task_id": "t2"}, project)

        assert len(results) == 1
        assert results[0]["module"] == "verify"
        mock_action.assert_called_once()

    def test_on_continue_fires(self, tmp_path):
        """Module with on_continue hook → action called when continue runs."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "continue.yaml").write_text(
            """name: continue
enabled: true
hooks:
  on_continue:
    action: continue_action
settings: {}
detect: {}
"""
        )

        mock_action = Mock(return_value={"refreshed": True})
        with patch("superharness.modules.runner._ACTION_REGISTRY", {"continue_action": mock_action}):
            results = run_hooks("on_continue", {"task_id": "t3"}, project)

        assert len(results) == 1
        assert results[0]["module"] == "continue"
        mock_action.assert_called_once()

    def test_module_failure_does_not_block_close(self, tmp_path, caplog):
        """If module action fails → warning logged, close still succeeds."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "failing.yaml").write_text(
            """name: failing
enabled: true
hooks:
  on_close:
    action: fail_action
settings: {}
detect: {}
"""
        )

        # Mock action that raises an exception
        def failing_action(context, settings):
            raise RuntimeError("Action failed")

        with patch("superharness.modules.runner._ACTION_REGISTRY", {"fail_action": failing_action}):
            results = run_hooks("on_close", {}, project)

        # Should return a result indicating failure, not crash
        assert len(results) == 1
        assert results[0]["success"] is False
        assert "error" in results[0]
        # Should log warning
        assert any("failing" in record.message.lower() for record in caplog.records)

    def test_multiple_modules_all_fire(self, tmp_path):
        """Two enabled modules with on_close → both fire."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "mod1.yaml").write_text(
            """name: mod1
enabled: true
hooks:
  on_close:
    action: action1
settings: {}
detect: {}
"""
        )

        (modules_dir / "mod2.yaml").write_text(
            """name: mod2
enabled: true
hooks:
  on_close:
    action: action2
settings: {}
detect: {}
"""
        )

        mock_action1 = Mock(return_value={"module": "1"})
        mock_action2 = Mock(return_value={"module": "2"})

        with patch("superharness.modules.runner._ACTION_REGISTRY", {
            "action1": mock_action1,
            "action2": mock_action2,
        }):
            results = run_hooks("on_close", {}, project)

        assert len(results) == 2
        mock_action1.assert_called_once()
        mock_action2.assert_called_once()

    def test_hook_receives_context(self, tmp_path):
        """Hook action receives task_id, summary, project_dir, actor."""
        from superharness.modules.runner import run_hooks

        project = tmp_path / "proj"
        project.mkdir()
        modules_dir = project / ".superharness" / "modules"
        modules_dir.mkdir(parents=True)

        (modules_dir / "ctx.yaml").write_text(
            """name: ctx
enabled: true
hooks:
  on_close:
    action: ctx_action
settings:
  key: value
detect: {}
"""
        )

        captured_context = {}
        captured_settings = {}

        def capture_action(context, settings):
            captured_context.update(context)
            captured_settings.update(settings)
            return {"ok": True}

        context = {
            "task_id": "task.123",
            "summary": "Test task",
            "project_dir": str(project),
            "actor": "claude-code",
        }

        with patch("superharness.modules.runner._ACTION_REGISTRY", {"ctx_action": capture_action}):
            run_hooks("on_close", context, project)

        # Verify context was passed through
        assert captured_context["task_id"] == "task.123"
        assert captured_context["summary"] == "Test task"
        assert captured_context["project_dir"] == str(project)
        assert captured_context["actor"] == "claude-code"

        # Verify settings were passed through
        assert captured_settings["key"] == "value"
