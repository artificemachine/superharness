"""Hermes Agent harness adapter.

Hermes (Nous Research) resolves its provider and default model from its own
config, so the model id is passed through unprefixed. It has no offline
model-list command, so discovery is empty and dispatch falls back to Hermes's
configured default unless the task names a model.
"""

from __future__ import annotations

from superharness.engine.model_discovery import DiscoveredModel
from superharness.harnesses.base import Invocation, build_generic_invocation


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
