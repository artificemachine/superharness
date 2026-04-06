"""Module manifest schema validation — Pydantic-based SDK v1 contracts.

This module is the authoritative source of the superharness Module SDK schema.
Extension authors should validate their manifests against these models before
shipping.

Usage::

    from superharness.modules.validator import validate_manifest, ManifestValidationError

    try:
        manifest = validate_manifest(yaml_data)
    except ManifestValidationError as exc:
        print(f"Invalid manifest: {exc}")
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, field_validator, ValidationError

from .constants import LIFECYCLE_EVENTS

# ── Schema versioning ──────────────────────────────────────────────────────────

CURRENT_SCHEMA_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1"})


# ── Pydantic models ────────────────────────────────────────────────────────────


class HookConfig(BaseModel):
    """Configuration for a single lifecycle hook entry in a module manifest."""

    model_config = ConfigDict(extra="allow")

    action: str
    priority: str = "normal"
    block_on: Optional[str] = None


class ModuleManifest(BaseModel):
    """Schema-validated representation of a module YAML manifest.

    This is the stable SDK v1 contract.  All fields not listed here are
    accepted (``extra="allow"``) so future versions can add fields without
    breaking existing validators.
    """

    model_config = ConfigDict(extra="allow")

    schema_version: str = CURRENT_SCHEMA_VERSION
    name: str
    description: str = ""
    enabled: bool = False
    detect: dict[str, Any] = {}
    hooks: dict[str, Any] = {}
    settings: dict[str, Any] = {}

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if v not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"Unsupported schema_version '{v}'. "
                f"Supported versions: {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
            )
        return v

    @field_validator("hooks")
    @classmethod
    def _check_hooks(cls, v: dict[str, Any]) -> dict[str, Any]:
        for hook_name, hook_config in v.items():
            # Validate hook name is a known lifecycle event
            if hook_name not in LIFECYCLE_EVENTS:
                raise ValueError(
                    f"Unknown lifecycle hook '{hook_name}'. "
                    f"Valid hooks: {LIFECYCLE_EVENTS}"
                )
            # Validate each hook has an 'action' field
            if isinstance(hook_config, dict) and "action" not in hook_config:
                raise ValueError(
                    f"Hook '{hook_name}' is missing required 'action' field"
                )
        return v


# ── Validation error ───────────────────────────────────────────────────────────


class ManifestValidationError(Exception):
    """Raised when a module manifest fails SDK schema validation.

    Attributes:
        module_name: Name of the module (from ``name`` field, or ``<unknown>``).
        errors: List of Pydantic error dicts describing each validation failure.
    """

    def __init__(self, module_name: str, errors: list[dict[str, Any]]) -> None:
        self.module_name = module_name
        self.errors = errors
        super().__init__(
            f"Module '{module_name}' manifest validation failed: {errors}"
        )


# ── Public validate function ───────────────────────────────────────────────────


def validate_manifest(data: dict[str, Any]) -> ModuleManifest:
    """Validate a module manifest dict against the SDK v1 schema.

    Args:
        data: Raw manifest data loaded from YAML.

    Returns:
        A validated :class:`ModuleManifest` instance.

    Raises:
        ManifestValidationError: If the manifest does not satisfy the schema.
    """
    try:
        return ModuleManifest.model_validate(data)
    except ValidationError as exc:
        module_name = data.get("name", "<unknown>") if isinstance(data, dict) else "<unknown>"
        raise ManifestValidationError(
            module_name=str(module_name),
            errors=exc.errors(),
        ) from exc
