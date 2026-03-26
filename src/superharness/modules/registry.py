"""Module registry — enable, disable, list, and query modules."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Path to built-in module templates
TEMPLATE_DIR = Path(__file__).parent.parent / "module_templates"


def available_modules() -> list[str]:
    """List all available module templates.

    Returns:
        List of module names (without .yaml extension)
    """
    if not TEMPLATE_DIR.exists():
        return []

    return sorted([f.stem for f in TEMPLATE_DIR.glob("*.yaml")])


def enabled_modules(project_dir: Path) -> list[str]:
    """List enabled modules in project.

    Args:
        project_dir: Project root directory

    Returns:
        List of enabled module names
    """
    modules_dir = project_dir / ".superharness" / "modules"

    if not modules_dir.exists():
        return []

    enabled = []
    for yaml_file in sorted(modules_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict) and data.get("enabled", False):
                    enabled.append(data.get("name", yaml_file.stem))
        except Exception as e:
            logger.warning(f"Failed to read {yaml_file.name}: {e}")
            continue

    return enabled


def enable_module(name: str, project_dir: Path) -> bool:
    """Enable a module by copying template to project.

    Args:
        name: Module name
        project_dir: Project root directory

    Returns:
        True if enabled successfully, False if template not found
    """
    # Check if template exists
    template_file = TEMPLATE_DIR / f"{name}.yaml"
    if not template_file.exists():
        logger.error(f"Module template '{name}' not found")
        logger.info(f"Available modules: {', '.join(available_modules())}")
        return False

    # Create modules directory
    modules_dir = project_dir / ".superharness" / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)

    # Target file
    target_file = modules_dir / f"{name}.yaml"

    # Read template
    try:
        with open(template_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to read template {name}: {e}")
        return False

    # Set enabled: true
    if isinstance(data, dict):
        data["enabled"] = True
    else:
        logger.error(f"Template {name} is not a valid YAML dict")
        return False

    # Write to project modules directory
    try:
        with open(target_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Module '{name}' enabled")
        return True
    except Exception as e:
        logger.error(f"Failed to write module file: {e}")
        return False


def disable_module(name: str, project_dir: Path) -> bool:
    """Disable a module by setting enabled: false.

    Args:
        name: Module name
        project_dir: Project root directory

    Returns:
        True if disabled successfully, False if module file not found
    """
    modules_dir = project_dir / ".superharness" / "modules"
    module_file = modules_dir / f"{name}.yaml"

    if not module_file.exists():
        # If file doesn't exist, module is not enabled anyway
        # This is idempotent — disabling a non-existent module succeeds
        logger.debug(f"Module '{name}' not found, already disabled")
        return True

    # Read current state
    try:
        with open(module_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to read module file: {e}")
        return False

    # Set enabled: false
    if isinstance(data, dict):
        data["enabled"] = False
    else:
        logger.error(f"Module file {name} is not a valid YAML dict")
        return False

    # Write back
    try:
        with open(module_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        logger.info(f"Module '{name}' disabled")
        return True
    except Exception as e:
        logger.error(f"Failed to write module file: {e}")
        return False


def module_info(name: str, project_dir: Path) -> dict[str, Any] | None:
    """Get detailed information about a module.

    Looks first in project modules, then in templates.

    Args:
        name: Module name
        project_dir: Project root directory

    Returns:
        Module metadata dict, or None if not found
    """
    # Check project modules first
    modules_dir = project_dir / ".superharness" / "modules"
    module_file = modules_dir / f"{name}.yaml"

    # If not in project, check templates
    if not module_file.exists():
        module_file = TEMPLATE_DIR / f"{name}.yaml"

    if not module_file.exists():
        logger.error(f"Module '{name}' not found")
        return None

    # Read and return module data
    try:
        with open(module_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
            else:
                logger.error(f"Module file {name} is not a valid YAML dict")
                return None
    except Exception as e:
        logger.error(f"Failed to read module {name}: {e}")
        return None
