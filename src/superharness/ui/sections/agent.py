"""Agent settings section — reads/writes autonomy and primary_agent in profile.yaml."""
from __future__ import annotations

from pathlib import Path

from superharness.ui.prompts import print_header, print_info
from superharness.ui.sections.base import run_section

_AUTONOMY_CHOICES = ["ai_driven"]
_AGENT_CHOICES    = ["claude-code", "codex-cli", "gemini-cli", "opencode"]


def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Show and optionally update agent behaviour settings."""
    from superharness.engine.profile import read_field

    print_header("Agent settings")

    current_autonomy = read_field(project_dir, "autonomy") or "ai_driven"
    current_agent    = read_field(project_dir, "primary_agent") or "claude-code"

    print_info(f"Autonomy:      {current_autonomy}")
    print_info(f"Primary agent: {current_agent}")

    # Autonomy — choose from list
    run_section(
        project_dir,
        field="autonomy",
        label="Autonomy mode",
        choices=_AUTONOMY_CHOICES,
        non_interactive=non_interactive,
        default_override=current_autonomy,
    )

    # Primary agent — free-text or choose from list
    run_section(
        project_dir,
        field="primary_agent",
        label="Primary agent",
        choices=None,
        non_interactive=non_interactive,
        default_override=current_agent,
    )
