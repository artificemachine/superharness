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

# Internal cache for loaded manifests
_manifest_cache: dict[str, AdapterManifest] = {}


def clear_manifest_cache() -> None:
    """Clear the internal adapter manifest cache."""
    _manifest_cache.clear()


class AdapterValidationError(Exception):
    """Raised when an adapter is unsupported or misconfigured."""


def _normalize_tier_value(value: Any, version: str = "*") -> dict[str, str]:
    """Normalize a manifest model_tier value to the canonical {id, label} form.

    Accepts three forms:
    - versioned: `{versions: {"*": {id, label}, "4.6": {id, label}, ...}}`
    - mapping:   `{id: <model-id>, label: <human-name>}`
    - legacy:    `<model-id>` string (label defaults to the same string)

    For versioned tiers, `version` selects the entry; falls back to `"*"`.
    Always returns a `{id, label}` dict.
    """
    if isinstance(value, dict):
        if "versions" in value:
            versions = value["versions"]
            entry = versions.get(version) or versions.get("*") or {}
            return _normalize_tier_value(entry)
        tier_id = str(value.get("id", "") or "").strip()
        label   = str(value.get("label", "") or "").strip()
        if not label:
            label = tier_id
        return {"id": tier_id, "label": label}
    text = str(value or "").strip()
    return {"id": text, "label": text}


@dataclass
class AdapterManifest:
    """Parsed adapter manifest.

    `model_tiers` values are always normalized to `{id, label}` mappings by
    `from_dict`, using the `"*"` (default) version when the tier uses the
    versioned schema.  Call `resolve_tier_version(tier, version)` to select
    a specific version (e.g. `"4.6"` for Opus 4.6 within the `max` tier).
    """
    name: str
    version: str
    description: str
    adapter_type: str  # "native" | "external"
    launcher_script: str
    capabilities: list[str] = field(default_factory=list)
    # tier_name -> {"id": str, "label": str}  (default/"*" version resolved)
    model_tiers: dict[str, dict[str, str]] = field(default_factory=dict)
    requires: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    # raw tier data preserved for resolve_tier_version()
    _raw_tier_data: dict[str, Any] = field(default_factory=dict, repr=False)

    def resolve_tier_version(self, tier: str, version: str = "*") -> dict[str, str]:
        """Resolve a tier + version to {id, label}.

        For versioned tiers (`{versions: {...}}`), looks up `version` then
        falls back to `"*"`.  For flat tiers (legacy or mapping form), the
        `version` parameter is ignored and the flat value is returned.
        Returns `{id: tier, label: tier}` if the tier is unknown (pass-through).
        """
        raw = self._raw_tier_data.get(tier)
        if raw is None:
            return {"id": tier, "label": tier}
        return _normalize_tier_value(raw, version=version)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdapterManifest":
        raw_tiers: dict[str, Any] = dict(data.get("model_tiers") or {})
        normalized_tiers = {
            str(name): _normalize_tier_value(val)
            for name, val in raw_tiers.items()
        }
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "1")),
            description=str(data.get("description", "")),
            adapter_type=str(data.get("type", "native")),
            launcher_script=str(data.get("launcher_script", "")),
            capabilities=list(data.get("capabilities") or []),
            model_tiers=normalized_tiers,
            requires=dict(data.get("requires") or {}),
            validation=dict(data.get("validation") or {}),
            _raw_tier_data=raw_tiers,
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
    if name in _manifest_cache:
        return _manifest_cache[name]

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

    manifest = AdapterManifest.from_dict(data)
    _manifest_cache[name] = manifest
    return manifest


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


def resolve_model(owner: str, tier: str, version: str = "*") -> dict[str, str]:
    """Resolve `(owner, tier, version)` to a concrete `{id, label}`.

    Resolution walks the adapter manifest's `model_tiers` table using the
    `resolve_tier_version` method.

    Falls back to `{id: tier, label: tier}` when:
    - the owner is unknown (no manifest)
    - the tier is unknown for that owner
    - the manifest fails to load for any reason
    """
    try:
        manifest = load_manifest(owner)
    except AdapterValidationError:
        return {"id": tier, "label": tier}

    return manifest.resolve_tier_version(tier, version=version)


def flagship(owner: str = "claude-code") -> str:
    """Return the current flagship (max-tier default) model id for *owner*.

    This is the single place that names the current-generation Opus model.
    All routing consumers (taxonomy, classifier, orchestrator, etc.) must
    call this instead of hardcoding a literal — so a model bump requires
    editing only the adapter manifest under adapter_manifests/.
    """
    return resolve_model(owner, "max")["id"]


def flagship_1m(owner: str = "claude-code") -> str:
    """Return the 1M-context variant of the flagship model id for *owner*."""
    return resolve_model(owner, "max-1m")["id"]


def fallback_flagship(owner: str = "claude-code") -> str:
    """Return the N-1 flagship model id (used as chain fallback / version pin)."""
    return resolve_model(owner, "max", version="4.7")["id"]


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
