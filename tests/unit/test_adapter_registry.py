"""Tests for the adapter registry (feat.adapter-registry-v1).

Covers:
- list_adapters returns built-in adapter names
- load_manifest for claude-code and codex-cli
- load_manifest for unknown adapter raises AdapterValidationError
- validate_adapter passes for native adapters when bin is present
- validate_adapter raises AdapterValidationError for unknown adapters
- resolve_launcher returns correct path when script exists
- resolve_launcher raises AdapterValidationError when script is missing
- Dispatch routing uses registry (no hard-coded if/else)
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from superharness.engine.adapter_registry import (
    MANIFEST_DIR,
    AdapterManifest,
    AdapterValidationError,
    adapter_info,
    list_adapters,
    load_manifest,
    resolve_launcher,
    validate_adapter,
)


class TestListAdapters:
    def test_returns_builtin_adapter_names(self):
        """list_adapters() returns at least claude-code and codex-cli."""
        names = list_adapters()
        assert "claude-code" in names
        assert "codex-cli" in names

    def test_returns_sorted_list(self):
        """list_adapters() returns names in sorted order."""
        names = list_adapters()
        assert names == sorted(names)


class TestLoadManifest:
    def test_load_claude_code_manifest(self):
        """load_manifest('claude-code') returns a valid AdapterManifest."""
        manifest = load_manifest("claude-code")
        assert isinstance(manifest, AdapterManifest)
        assert manifest.name == "claude-code"
        assert manifest.launcher_script == "delegate-to-claude.sh"
        assert manifest.adapter_type == "native"
        assert manifest.version == "1"

    def test_load_codex_cli_manifest(self):
        """load_manifest('codex-cli') returns a valid AdapterManifest."""
        manifest = load_manifest("codex-cli")
        assert isinstance(manifest, AdapterManifest)
        assert manifest.name == "codex-cli"
        assert manifest.launcher_script == "delegate-to-codex.sh"
        assert manifest.adapter_type == "native"

    def test_load_unknown_adapter_raises_error(self):
        """load_manifest for unknown adapter raises AdapterValidationError."""
        with pytest.raises(AdapterValidationError, match="Unknown adapter 'nonexistent-agent'"):
            load_manifest("nonexistent-agent")

    def test_error_message_lists_available_adapters(self):
        """Error for unknown adapter includes available adapter names."""
        with pytest.raises(AdapterValidationError) as exc_info:
            load_manifest("no-such-adapter")
        msg = str(exc_info.value)
        assert "claude-code" in msg or "Available adapters" in msg

    def test_manifest_has_model_tiers(self):
        """Loaded manifest includes model_tiers mapping."""
        manifest = load_manifest("claude-code")
        assert "mini" in manifest.model_tiers
        assert "standard" in manifest.model_tiers
        assert "max" in manifest.model_tiers

    def test_manifest_has_capabilities(self):
        """Loaded manifest lists capabilities."""
        manifest = load_manifest("claude-code")
        assert len(manifest.capabilities) > 0


class TestValidateAdapter:
    def test_unknown_adapter_raises_error(self):
        """validate_adapter for unknown adapter raises AdapterValidationError."""
        with pytest.raises(AdapterValidationError):
            validate_adapter("no-such-agent")

    def test_claude_code_passes_when_bin_present(self):
        """validate_adapter('claude-code') passes when 'claude' is in PATH."""
        with patch("shutil.which", return_value="/usr/local/bin/claude"):
            manifest = validate_adapter("claude-code")
        assert manifest.name == "claude-code"

    def test_claude_code_fails_when_bin_missing(self):
        """validate_adapter('claude-code') raises when 'claude' binary is absent."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(AdapterValidationError, match="claude"):
                validate_adapter("claude-code")

    def test_codex_cli_passes_when_bin_present(self):
        """validate_adapter('codex-cli') passes when 'codex' is in PATH."""
        with patch("shutil.which", return_value="/usr/local/bin/codex"):
            manifest = validate_adapter("codex-cli")
        assert manifest.name == "codex-cli"


class TestResolveLauncher:
    def test_resolve_claude_code_launcher(self, tmp_path):
        """resolve_launcher returns path to delegate-to-claude.sh."""
        script = tmp_path / "delegate-to-claude.sh"
        script.write_text("#!/bin/bash\n")
        launcher = resolve_launcher("claude-code", str(tmp_path))
        assert launcher == str(script)

    def test_resolve_codex_cli_launcher(self, tmp_path):
        """resolve_launcher returns path to delegate-to-codex.sh."""
        script = tmp_path / "delegate-to-codex.sh"
        script.write_text("#!/bin/bash\n")
        launcher = resolve_launcher("codex-cli", str(tmp_path))
        assert launcher == str(script)

    def test_missing_script_raises_error(self, tmp_path):
        """resolve_launcher raises AdapterValidationError when script is absent."""
        # Don't create the script file
        with pytest.raises(AdapterValidationError, match="launcher script not found"):
            resolve_launcher("claude-code", str(tmp_path))

    def test_unknown_adapter_raises_error(self, tmp_path):
        """resolve_launcher for unknown adapter raises AdapterValidationError."""
        with pytest.raises(AdapterValidationError, match="Unknown adapter"):
            resolve_launcher("no-such-agent", str(tmp_path))


class TestAdapterInfo:
    def test_info_returns_valid_flag(self):
        """adapter_info returns 'valid' key."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            info = adapter_info("claude-code")
        assert "valid" in info
        assert "issues" in info

    def test_info_unknown_raises_error(self):
        """adapter_info for unknown adapter raises AdapterValidationError."""
        with pytest.raises(AdapterValidationError):
            adapter_info("no-such-agent")


class TestDispatchUsesRegistry:
    """Integration-level: dispatch routing no longer uses hard-coded if/else."""

    def test_dispatch_imports_adapter_registry(self):
        """inbox_dispatch module can be imported without error."""
        from superharness.commands import inbox_dispatch
        # The module should import cleanly
        assert inbox_dispatch is not None

    def test_dispatch_does_not_hardcode_target_strings(self):
        """inbox_dispatch._do_dispatch uses resolve_launcher, not a hard-coded if/else."""
        import inspect
        from superharness.commands import inbox_dispatch
        source = inspect.getsource(inbox_dispatch._do_dispatch)
        # Should not have a raw if/else that hard-codes agent names directly
        # (resolve_launcher call should be present instead)
        assert "resolve_launcher" in source or "adapter_registry" in source

    def test_dispatch_unknown_target_fails_gracefully(self, tmp_path):
        """Dispatching to an unknown target fails with a clear validation error."""
        import json
        inbox_file = tmp_path / "inbox.yaml"
        contract_file = tmp_path / "contract.yaml"

        # Create a minimal inbox with an unknown target
        inbox_data = {
            "items": [{
                "id": "test-001",
                "to": "unknown-agent-xyz",
                "task": "test.task",
                "status": "pending",
                "project": str(tmp_path),
            }]
        }
        import yaml
        inbox_file.write_text(yaml.dump(inbox_data))

        from superharness.commands.inbox_dispatch import _do_dispatch, _MkdirLock
        lock = _MkdirLock(str(tmp_path / "inbox.yaml.lock.d"))

        import sys
        from unittest.mock import patch

        # Mock subprocess.run to return the inbox item
        mock_item = json.dumps({
            "id": "test-001",
            "to": "unknown-agent-xyz",
            "task": "test.task",
            "status": "pending",
            "project": str(tmp_path),
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout=mock_item,
                stderr="",
            )
            rc = _do_dispatch(
                inbox_file=str(inbox_file),
                contract_file=str(contract_file),
                project_dir=str(tmp_path),
                target_filter=None,
                print_only=False,
                non_interactive=False,
                codex_bypass=False,
                launcher_timeout=0,
                script_dir="/fake/scripts",
                lock=lock,
            )
        # Should return non-zero for unknown adapter
        assert rc != 0
