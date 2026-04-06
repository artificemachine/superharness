"""Superharness Module SDK v1 — public extension interface.

This is the stable, documented entry-point for extension authors.  Import from
here rather than from the internal sub-modules so that refactors inside the
module system do not break third-party extensions.

Lifecycle contract
------------------
Modules hook into named lifecycle events fired by the harness:

* ``on_close``        — task is being closed / completed
* ``on_verify``       — task verification is running
* ``on_continue``     — task is being resumed
* ``on_delegate``     — task is being delegated to an agent
* ``on_watcher_tick`` — periodic watcher poll (background automation)

Action signature
----------------
Every action registered with :func:`register_action` must accept exactly two
positional arguments and return a :class:`dict`::

    def my_action(context: dict, settings: dict) -> dict:
        ...
        return {"success": True}

*context* keys (always present when the harness fires the hook):
    task_id, summary, project_dir, actor

*settings* is the ``settings`` mapping from the module's YAML manifest.

The return dict must contain at minimum ``{"success": bool}``.  Extra keys are
forwarded to the harness result log and may be surfaced in the dashboard.

Minimal manifest (schema_version 1)
------------------------------------
.. code-block:: yaml

    schema_version: "1"
    name: my-module
    description: "What this module does"
    enabled: false          # user opts in manually
    detect: {}              # optional availability detection hints
    hooks:
      on_close:
        action: my_action   # must be registered via register_action()
    settings:
      my_key: default_value

Extension registration
-----------------------
Third-party packages register their actions during their own ``__init__``::

    from superharness.modules.sdk import register_action
    from .my_module import my_action

    register_action("my_action", my_action)

Schema validation
-----------------
::

    from superharness.modules.sdk import validate_manifest, ManifestValidationError

    try:
        manifest = validate_manifest(yaml_data)
    except ManifestValidationError as exc:
        print(exc.errors)
"""
from __future__ import annotations

from .constants import LIFECYCLE_EVENTS
from .loader import load_modules
from .registry import available_modules, disable_module, enable_module, enabled_modules
from .runner import register_action, run_hooks
from .validator import (
    CURRENT_SCHEMA_VERSION,
    SUPPORTED_SCHEMA_VERSIONS,
    HookConfig,
    ManifestValidationError,
    ModuleManifest,
    validate_manifest,
)

__all__ = [
    # Lifecycle constants
    "LIFECYCLE_EVENTS",
    "CURRENT_SCHEMA_VERSION",
    "SUPPORTED_SCHEMA_VERSIONS",
    # Schema models
    "ModuleManifest",
    "HookConfig",
    # Validation
    "ManifestValidationError",
    "validate_manifest",
    # Action registration
    "register_action",
    # Hook execution
    "run_hooks",
    # Module management
    "load_modules",
    "available_modules",
    "enabled_modules",
    "enable_module",
    "disable_module",
]
