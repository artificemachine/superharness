"""Gemini CLI harness adapter. See docs/PLAN-steal-omnigent.md iteration 6."""
from __future__ import annotations

from superharness.harnesses.base import Invocation, build_generic_invocation


class GeminiHarness:
    name = "gemini-cli"

    def build_invocation(
        self, task: dict, project_dir: str, non_interactive: bool
    ) -> Invocation:
        return build_generic_invocation(self.name, task, project_dir, non_interactive)
