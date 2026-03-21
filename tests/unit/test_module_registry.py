"""Tests for module registry (enable, disable, list modules)."""
from __future__ import annotations

import pytest
from pathlib import Path

from superharness.modules.registry import (
    available_modules,
    enabled_modules,
    enable_module,
    disable_module,
    module_info,
)


class TestModuleRegistry:
    """Test module registry operations."""

    def test_list_available_modules(self):
        """Lists all built-in module templates."""
        modules = available_modules()
        assert isinstance(modules, list)
        assert len(modules) > 0
        # At least obsidian should be available (iteration 3)
        # For now, just check that we can list templates

    def test_list_enabled_modules(self, tmp_path: Path):
        """Lists only modules enabled in .superharness/modules/."""
        # No modules enabled initially
        assert enabled_modules(tmp_path) == []

        # Create .superharness/modules/ with one enabled module
        modules_dir = tmp_path / ".superharness" / "modules"
        modules_dir.mkdir(parents=True, exist_ok=True)

        # Write enabled module
        enabled_yaml = modules_dir / "test-enabled.yaml"
        enabled_yaml.write_text(
            "name: test-enabled\nenabled: true\nhooks: {}\nsettings: {}\ndetect: {}\n"
        )

        # Write disabled module
        disabled_yaml = modules_dir / "test-disabled.yaml"
        disabled_yaml.write_text(
            "name: test-disabled\nenabled: false\nhooks: {}\nsettings: {}\ndetect: {}\n"
        )

        # Only enabled module should be listed
        result = enabled_modules(tmp_path)
        assert result == ["test-enabled"]

    def test_enable_copies_template(self, tmp_path: Path):
        """shux enhance enable <module> → copies template to modules/."""
        # Create a fake template directory
        from superharness.modules import registry
        original_template_dir = registry.TEMPLATE_DIR

        # Use tmp_path as template dir for this test
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        registry.TEMPLATE_DIR = template_dir

        # Create a template
        test_template = template_dir / "test-module.yaml"
        test_template.write_text(
            "name: test-module\nenabled: false\nhooks: {}\nsettings: {}\ndetect: {}\n"
        )

        # Create project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Enable the module
            result = enable_module("test-module", project_dir)
            assert result is True

            # Check that file was copied
            modules_dir = project_dir / ".superharness" / "modules"
            copied_file = modules_dir / "test-module.yaml"
            assert copied_file.exists()

            # Check that enabled: true was set
            content = copied_file.read_text()
            assert "enabled: true" in content

        finally:
            # Restore original template dir
            registry.TEMPLATE_DIR = original_template_dir

    def test_enable_already_enabled_is_noop(self, tmp_path: Path):
        """Enabling an already-enabled module → no-op, idempotent."""
        from superharness.modules import registry
        original_template_dir = registry.TEMPLATE_DIR

        # Use tmp_path as template dir for this test
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        registry.TEMPLATE_DIR = template_dir

        # Create a template
        test_template = template_dir / "test-module.yaml"
        test_template.write_text(
            "name: test-module\nenabled: false\nhooks: {}\nsettings: {}\ndetect: {}\n"
        )

        # Create project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Enable once
            result1 = enable_module("test-module", project_dir)
            assert result1 is True

            # Enable again — should be idempotent (no error, returns True)
            result2 = enable_module("test-module", project_dir)
            assert result2 is True

        finally:
            # Restore original template dir
            registry.TEMPLATE_DIR = original_template_dir

    def test_disable_sets_enabled_false(self, tmp_path: Path):
        """shux enhance disable <module> → sets enabled: false in YAML."""
        from superharness.modules import registry
        original_template_dir = registry.TEMPLATE_DIR

        # Use tmp_path as template dir for this test
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        registry.TEMPLATE_DIR = template_dir

        # Create a template
        test_template = template_dir / "test-module.yaml"
        test_template.write_text(
            "name: test-module\nenabled: false\nhooks: {}\nsettings: {}\ndetect: {}\n"
        )

        # Create project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Enable the module
            enable_module("test-module", project_dir)

            # Verify it's enabled
            assert "test-module" in enabled_modules(project_dir)

            # Disable the module
            result = disable_module("test-module", project_dir)
            assert result is True

            # Verify it's no longer in enabled list
            assert "test-module" not in enabled_modules(project_dir)

            # Verify file still exists but enabled: false
            modules_dir = project_dir / ".superharness" / "modules"
            module_file = modules_dir / "test-module.yaml"
            assert module_file.exists()
            content = module_file.read_text()
            assert "enabled: false" in content

        finally:
            # Restore original template dir
            registry.TEMPLATE_DIR = original_template_dir

    def test_disable_already_disabled_is_noop(self, tmp_path: Path):
        """Disabling already-disabled → no-op, idempotent."""
        from superharness.modules import registry
        original_template_dir = registry.TEMPLATE_DIR

        # Use tmp_path as template dir for this test
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        registry.TEMPLATE_DIR = template_dir

        # Create a template
        test_template = template_dir / "test-module.yaml"
        test_template.write_text(
            "name: test-module\nenabled: false\nhooks: {}\nsettings: {}\ndetect: {}\n"
        )

        # Create project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Enable then disable
            enable_module("test-module", project_dir)
            disable_module("test-module", project_dir)

            # Disable again — should be idempotent
            result = disable_module("test-module", project_dir)
            assert result is True

        finally:
            # Restore original template dir
            registry.TEMPLATE_DIR = original_template_dir

    def test_enable_unknown_module_fails(self, tmp_path: Path):
        """shux enhance enable nonexistent → error."""
        from superharness.modules import registry
        original_template_dir = registry.TEMPLATE_DIR

        # Use tmp_path as template dir for this test
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        registry.TEMPLATE_DIR = template_dir

        # Create project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Try to enable non-existent module
            result = enable_module("nonexistent-module", project_dir)
            assert result is False

        finally:
            # Restore original template dir
            registry.TEMPLATE_DIR = original_template_dir

    def test_info_shows_module_details(self, tmp_path: Path):
        """shux enhance info <module> → shows description, detection, settings."""
        from superharness.modules import registry
        original_template_dir = registry.TEMPLATE_DIR

        # Use tmp_path as template dir for this test
        template_dir = tmp_path / "templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        registry.TEMPLATE_DIR = template_dir

        # Create a template with rich metadata
        test_template = template_dir / "test-module.yaml"
        test_template.write_text("""name: test-module
description: "Test module for demonstration"
enabled: false
detect:
  bin: test-binary
  env: TEST_VAR
hooks:
  on_close:
    action: test_action
settings:
  option1: value1
  option2: value2
""")

        # Create project dir
        project_dir = tmp_path / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Get module info
            info = module_info("test-module", project_dir)
            assert info is not None
            assert info["name"] == "test-module"
            assert info["description"] == "Test module for demonstration"
            assert "detect" in info
            assert "hooks" in info
            assert "settings" in info

        finally:
            # Restore original template dir
            registry.TEMPLATE_DIR = original_template_dir
