"""Module loader — loads YAML module definitions."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Avoid circular import: import validator lazily inside load_modules
def _validate(data: dict[str, Any], file_name: str) -> bool:
    """Validate manifest data against SDK v1 schema.

    Returns True if valid, False (and logs a warning) if invalid.
    """
    try:
        from .validator import ManifestValidationError, validate_manifest

        validate_manifest(data)
        return True
    except Exception as exc:  # ManifestValidationError or unexpected
        name = data.get("name", file_name) if isinstance(data, dict) else file_name
        logger.warning(
            f"Module '{name}' failed SDK v1 manifest validation and will be skipped: {exc}"
        )
        return False


@dataclass
class Module:
    """Represents a loaded module definition."""

    name: str
    enabled: bool
    hooks: dict[str, Any]
    settings: dict[str, Any]
    detect: dict[str, Any]
    file_path: Path


def _safe_yaml_load(path: Path) -> dict[str, Any] | None:
    """Load YAML file safely, return None on error."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.warning(f"Module {path.name} is not a valid YAML dict, skipping")
                return None
            return data
    except yaml.YAMLError as e:
        logger.warning(f"Failed to parse {path.name}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Failed to load {path.name}: {e}")
        return None


def load_modules(project_dir: Path) -> list[Module]:
    """Load all enabled modules from .superharness/modules/*.yaml.

    Args:
        project_dir: Project root directory containing .superharness/

    Returns:
        List of Module objects for enabled modules only
    """
    modules_dir = project_dir / ".superharness" / "modules"

    # If modules directory doesn't exist, return empty list
    if not modules_dir.exists():
        return []

    loaded_modules = []

    # Iterate through all YAML files in modules directory
    for yaml_file in sorted(modules_dir.glob("*.yaml")):
        data = _safe_yaml_load(yaml_file)
        if data is None:
            continue

        # Validate manifest against SDK v1 schema before loading
        if not _validate(data, yaml_file.stem):
            continue

        # Extract required fields with defaults
        name = data.get("name", yaml_file.stem)
        enabled = data.get("enabled", False)

        # Skip disabled modules
        if not enabled:
            continue

        hooks = data.get("hooks", {})
        settings = data.get("settings", {})
        detect = data.get("detect", {})

        module = Module(
            name=name,
            enabled=enabled,
            hooks=hooks,
            settings=settings,
            detect=detect,
            file_path=yaml_file,
        )
        loaded_modules.append(module)

    return loaded_modules
