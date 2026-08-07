"""OpenCode harness adapter. See docs/PLAN-steal-omnigent.md iteration 6.

Iteration 2 of PLAN-dynamic-model-selection.md adds native model discovery:
``opencode models`` prints one ``provider/model-id`` per line; we parse that
into ``DiscoveredModel`` entries.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from superharness.engine.model_discovery import DiscoveredModel
from superharness.harnesses.base import Invocation, build_generic_invocation

_OPENCODE_MODELS_TIMEOUT_SECONDS = 10


def _parse_opencode_models_output(text: str) -> list[DiscoveredModel]:
    """Parse plain-text ``opencode models`` output.

    One ``provider/model-id`` per line. Junk lines (banners, warnings,
    blank lines) are skipped. Label defaults to the full id — the plain
    text output carries no separate label.
    """
    models: list[DiscoveredModel] = []
    now = datetime.now(timezone.utc)
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # A model id contains exactly one '/' separating provider from id.
        if "/" not in line:
            continue
        models.append(
            DiscoveredModel(
                id=line,
                label=line,
                source="native",
                auth_mode="unknown",
                probed_at=now,
            )
        )
    return models


class OpencodeHarness:
    name = "opencode"

    def discover_models(self, auth_mode: str = "unknown") -> list[DiscoveredModel]:
        """Native discovery: ``opencode models`` → parsed model list.

        Never raises: a missing binary, timeout, or malformed output all
        yield an empty list so dispatch falls back to the manifest.
        """
        try:
            result = subprocess.run(
                ["opencode", "models"],
                capture_output=True,
                text=True,
                timeout=_OPENCODE_MODELS_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        if result.returncode != 0:
            return []
        models = _parse_opencode_models_output(result.stdout)
        # Tag auth_mode onto entries (all entries share the caller's mode).
        if auth_mode != "unknown":
            models = [
                DiscoveredModel(
                    id=m.id, label=m.label, source=m.source,
                    auth_mode=auth_mode, probed_at=m.probed_at,
                )
                for m in models
            ]
        return models

    def build_invocation(
        self, task: dict, project_dir: str, non_interactive: bool
    ) -> Invocation:
        return build_generic_invocation(self.name, task, project_dir, non_interactive)
