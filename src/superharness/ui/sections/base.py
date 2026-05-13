"""Shared read-prompt-write skeleton for onboard sections.

Each section module is a thin wrapper around run_section() plus any
section-specific logic (e.g. stale-path scanning, platform dispatch).

Usage:
    from superharness.ui.sections.base import run_section

    def run(project_dir: Path, non_interactive: bool = False) -> None:
        run_section(
            project_dir,
            field="autonomy",
            label="Autonomy mode",
            choices=["supervised", "full-auto", "approval-gated"],
            non_interactive=non_interactive,
        )
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


def run_section(
    project_dir: Path,
    field: str,
    label: str,
    choices: list[str] | None = None,
    non_interactive: bool = False,
    default_override: Optional[str] = None,
) -> str:
    """Read current value, prompt user (unless headless), write back.

    Args:
        project_dir: Root of the project (.superharness/ lives here).
        field: Key in profile.yaml to read and write.
        label: Human-readable label shown in the prompt.
        choices: If provided, use prompt_choice(). Otherwise use prompt().
        non_interactive: Skip prompting entirely — keep current value.
        default_override: If set, use this as the default instead of
            the value read from profile.yaml.

    Returns:
        The (possibly updated) value that was written.
    """
    from superharness.engine.profile import read_field, write_field
    from superharness.ui.prompts import print_info

    current = read_field(project_dir, field)
    effective_default = default_override if default_override is not None else current

    if non_interactive:
        # Headless: ensure the field exists in profile.yaml (backfill only)
        if not current:
            # Only write if missing — do not overwrite user's existing value
            if effective_default:
                write_field(project_dir, field, effective_default)
                return effective_default
        return current or effective_default

    # Interactive path
    if choices:
        from superharness.ui.prompts import prompt_choice
        # Find default index
        try:
            default_idx = choices.index(effective_default)
        except ValueError:
            default_idx = 0
        idx = prompt_choice(f"{label} (current: {effective_default or 'unset'})", choices, default=default_idx)
        new_value = choices[idx]
    else:
        from superharness.ui.prompts import prompt
        new_value = prompt(label, default=effective_default or "")

    write_field(project_dir, field, new_value)
    print_info(f"{label}: {new_value}")
    return new_value
