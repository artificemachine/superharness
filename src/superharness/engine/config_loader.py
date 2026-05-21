from __future__ import annotations

import importlib.resources
import os
import yaml
from typing import Any

import logging
logger = logging.getLogger(__name__)

def load_yaml_config(
    bundled_pkg: str,
    bundled_filename: str,
    project_dir: str | None,
    project_filename: str,
    fallback: Any
) -> Any:
    """Load a YAML config with bundled defaults and project-level overrides.
    
    1. Load bundled YAML from the package.
    2. If project_dir is provided, deep-merge .superharness/<project_filename> over it.
    3. Fall back to `fallback` on any fatal error during loading.
    """
    try:
        # 1. Load bundled
        try:
            traversable = importlib.resources.files(bundled_pkg).joinpath(bundled_filename)
            with traversable.open("r") as f:
                config = yaml.safe_load(f) or {}
        except (FileNotFoundError, ImportError, TypeError, OSError):
            config = {}

        # 2. Project override
        if project_dir:
            project_path = os.path.join(project_dir, ".superharness", project_filename)
            if os.path.exists(project_path):
                try:
                    with open(project_path, "r") as f:
                        project_config = yaml.safe_load(f) or {}
                    config = _deep_merge(config, project_config)
                except (yaml.YAMLError, OSError):
                    pass # Fall back to bundled/fallback

        if not config:
            return fallback
            
        return config

    except Exception as e:
        logger.warning("config_loader.py unexpected error: %s", e, exc_info=True)
        return fallback

def _deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
