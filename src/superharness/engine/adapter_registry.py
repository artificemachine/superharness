"""Adapter registry — manifest-driven routing for agent runtimes.

Provides a versioned registry of adapter manifests (YAML files) for
agent runtimes (claude-code, codex-cli, and future external adapters).
All dispatch paths use this registry to resolve launchers, validate
adapters, and surface capability information.
"""
from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Directory containing built-in adapter manifests
MANIFEST_DIR = Path(__file__).parent.parent / "adapter_manifests"

REGISTRY_VERSION = "1"


class AdapterValidationError(Exception):
    """Raised when an adapter is unsupported or misconfigured."""


@dataclass
class AdapterManifest:
    """Parsed adapter manifest."""
    name: str
    version: str
    description: str
    adapter_type: str  # "native" | "external"
    launcher_script: str
    capabilities: list[str] = field(default_factory=list)
    model_tiers: dict[str, str] = field(default_factory=dict)
    requires: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdapterManifest":
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "1")),
            description=str(data.get("description", "")),
            adapter_type=str(data.get("type", "native")),
            launcher_script=str(data.get("launcher_script", "")),
            capabilities=list(data.get("capabilities") or []),
            model_tiers=dict(data.get("model_tiers") or {}),
            requires=dict(data.get("requires") or {}),
            validation=dict(data.get("validation") or {}),
        )


def list_adapters() -> list[str]:
    """Return names of all built-in adapter manifests."""
    if not MANIFEST_DIR.exists():
        return []
    return sorted(f.stem for f in MANIFEST_DIR.glob("*.yaml"))


def load_manifest(name: str) -> AdapterManifest:
    """Load and parse an adapter manifest by name.

    Raises:
        AdapterValidationError: if the manifest does not exist or is malformed.
    """
    manifest_file = MANIFEST_DIR / f"{name}.yaml"
    if not manifest_file.exists():
        available = list_adapters()
        raise AdapterValidationError(
            f"Unknown adapter '{name}'. Available adapters: {', '.join(available) or 'none'}"
        )
    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        raise AdapterValidationError(f"Failed to read adapter manifest '{name}': {e}") from e

    if not isinstance(data, dict):
        raise AdapterValidationError(f"Adapter manifest '{name}' is not a valid YAML dict")

    return AdapterManifest.from_dict(data)


def validate_adapter(name: str) -> AdapterManifest:
    """Load and validate an adapter manifest.

    Checks that the adapter exists, is parseable, and passes runtime checks
    (e.g. required binaries are present).

    Returns:
        The validated AdapterManifest.

    Raises:
        AdapterValidationError: with a clear message if validation fails.
    """
    manifest = load_manifest(name)

    # Check required binary
    if manifest.validation.get("check_bin", False):
        required_bin = manifest.requires.get("bin")
        if required_bin and not shutil.which(required_bin):
            raise AdapterValidationError(
                f"Adapter '{name}' requires '{required_bin}' but it is not found in PATH. "
                f"Install '{required_bin}' or use a different adapter."
            )

    # Check required env vars
    if manifest.validation.get("check_env", False):
        for env_var in manifest.requires.get("env") or []:
            if not os.environ.get(env_var):
                raise AdapterValidationError(
                    f"Adapter '{name}' requires environment variable '{env_var}' which is not set."
                )

    return manifest


def resolve_launcher(name: str, scripts_dir: str) -> str:
    """Resolve the launcher script path for an adapter.

    Args:
        name: Adapter name (e.g. 'claude-code', 'codex-cli')
        scripts_dir: Directory containing launcher scripts

    Returns:
        Absolute path to the launcher script.

    Raises:
        AdapterValidationError: if the adapter is unknown or its launcher is missing.
    """
    manifest = load_manifest(name)
    launcher_path = os.path.join(scripts_dir, manifest.launcher_script)
    if not os.path.exists(launcher_path):
        raise AdapterValidationError(
            f"Adapter '{name}' launcher script not found: {launcher_path}"
        )
    return launcher_path


def adapter_info(name: str) -> dict[str, Any]:
    """Return structured info about an adapter for display/scripting.

    Raises:
        AdapterValidationError: if the adapter is unknown.
    """
    manifest = load_manifest(name)

    # Determine validation status
    issues: list[str] = []
    if manifest.validation.get("check_bin", False):
        required_bin = manifest.requires.get("bin")
        if required_bin and not shutil.which(required_bin):
            issues.append(f"Binary '{required_bin}' not found in PATH")
    if manifest.validation.get("check_env", False):
        for env_var in manifest.requires.get("env") or []:
            if not os.environ.get(env_var):
                issues.append(f"Environment variable '{env_var}' not set")

    return {
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "type": manifest.adapter_type,
        "launcher_script": manifest.launcher_script,
        "capabilities": manifest.capabilities,
        "model_tiers": manifest.model_tiers,
        "requires": manifest.requires,
        "valid": len(issues) == 0,
        "issues": issues,
    }
