"""Pi harness adapter for the intentionally inert Pi launcher.

Model discovery uses Pi's offline list command only.  It never launches an
agent turn or contacts a provider.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from superharness.engine.model_discovery import DiscoveredModel
from superharness.harnesses.base import Invocation, build_generic_invocation

_PI_MODELS_COMMAND = (
    "pi",
    "--offline",
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--list-models",
)
_PI_MODELS_TIMEOUT_SECONDS = 10


def _parse_pi_models_output(text: str) -> list[str]:
    """Parse one complete Pi model-list stream into sorted provider/model IDs."""
    if not isinstance(text, str):
        return []

    lines = [line.split() for line in text.splitlines() if line.split()]
    for row_index, header in enumerate(lines):
        if "provider" not in header or "model" not in header:
            continue

        provider_index = header.index("provider")
        model_index = header.index("model")
        required_columns = len(header)
        models = {
            f"{row[provider_index]}/{row[model_index]}"
            for row in lines[row_index + 1 :]
            if len(row) >= required_columns
            and row[provider_index]
            and row[model_index]
        }
        return sorted(models)
    return []


class PiHarness:
    name = "pi"

    def discover_models(self, auth_mode: str = "unknown") -> list[DiscoveredModel]:
        """Discover locally listed Pi models without raising on any failure."""
        try:
            result = subprocess.run(
                _PI_MODELS_COMMAND,
                capture_output=True,
                text=True,
                timeout=_PI_MODELS_TIMEOUT_SECONDS,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []
        if result.returncode != 0:
            return []

        # Pi 0.73.1 may write the complete table to stderr.  Parse each
        # successful stream independently so incomplete fragments never combine.
        model_ids = _parse_pi_models_output(result.stdout)
        if not model_ids:
            model_ids = _parse_pi_models_output(result.stderr)
        if not model_ids:
            return []

        now = datetime.now(timezone.utc)
        return [
            DiscoveredModel(
                id=model_id,
                label=model_id,
                source="native",
                auth_mode=auth_mode,
                probed_at=now,
            )
            for model_id in model_ids
        ]

    def build_invocation(
        self, task: dict, project_dir: str, non_interactive: bool
    ) -> Invocation:
        return build_generic_invocation(self.name, task, project_dir, non_interactive)
