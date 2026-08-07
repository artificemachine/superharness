"""OpenCode harness adapter. See docs/PLAN-steal-omnigent.md iteration 6."""

from __future__ import annotations

from superharness.harnesses.base import Invocation, build_generic_invocation


class OpencodeHarness:
    name = "opencode"

    def discover_models(self, auth_mode: str = "unknown") -> list:
        """Iteration 1: no-op — native discovery lands in iteration 2."""
        return []

    def build_invocation(
        self, task: dict, project_dir: str, non_interactive: bool
    ) -> Invocation:
        return build_generic_invocation(self.name, task, project_dir, non_interactive)
