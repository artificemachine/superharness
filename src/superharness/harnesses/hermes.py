"""Hermes Agent harness adapter.

Hermes (Nous Research) resolves its provider and default model from its own
config, so the model id is passed through unprefixed. It has no offline
model-list command, so discovery is empty and dispatch falls back to the
manifest tiers unless runtime bindings or the task name a model.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from superharness.engine.model_discovery import DiscoveredModel
from superharness.harnesses.base import Invocation, build_generic_invocation

# API keys read from the macOS Keychain, stored as generic passwords named
# `env:<VAR>`. delegate-to-hermes.sh does the same lookup for worker runs.
KEYCHAIN_ENV_VARS = ("DEEPSEEK_API_KEY",)
_KEYCHAIN_TIMEOUT_SECONDS = 10


def keychain_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Return a copy of ``base`` (default: os.environ) with Keychain API keys added.

    A variable already set wins. A missing `security` binary, a missing entry
    or a failed lookup leaves the variable unset, so Hermes falls back to its
    own config. The value is never logged or placed on a command line.
    """
    env = dict(os.environ if base is None else base)
    if shutil.which("security") is None:
        return env
    account = env.get("HERMES_KEYCHAIN_ACCOUNT") or env.get("USER") or ""
    for var in KEYCHAIN_ENV_VARS:
        if env.get(var):
            continue
        try:
            result = subprocess.run(
                ["security", "find-generic-password", "-a", account, "-s", f"env:{var}", "-w"],
                capture_output=True,
                text=True,
                timeout=_KEYCHAIN_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            continue
        value = (result.stdout or "").strip()
        if result.returncode == 0 and value:
            env[var] = value
    return env


class HermesHarness:
    name = "hermes"

    def discover_models(self, auth_mode: str = "unknown") -> list[DiscoveredModel]:
        return []

    def build_invocation(
        self, task: dict, project_dir: str, non_interactive: bool
    ) -> Invocation:
        return build_generic_invocation(
            self.name, task, project_dir, non_interactive, prefix_model=False
        )
