"""Project identity section — reads/writes project_name and stack in profile.yaml."""
from __future__ import annotations

from pathlib import Path

from superharness.ui.prompts import print_header, print_info
from superharness.ui.sections.base import run_section


def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Show and optionally update project identity fields."""
    print_header("Project identity")

    # Auto-detect stack (read-only, never prompted)
    _stack = _detect_stack(project_dir)

    # Read current project_name; default to directory name
    from superharness.engine.profile import read_field
    current_name = read_field(project_dir, "project_name") or project_dir.name

    print_info(f"Directory: {project_dir.name}")
    print_info(f"Stack:     {_stack}")
    print_info(f"Name:      {current_name}")

    # Update project_name (prompted in interactive mode)
    run_section(
        project_dir,
        field="project_name",
        label="Project name",
        choices=None,
        non_interactive=non_interactive,
        default_override=current_name,
    )

    # Always persist stack (auto-detected, not prompted)
    from superharness.engine.profile import write_field
    write_field(project_dir, "stack", _stack)
    write_field(project_dir, "status", read_field(project_dir, "status") or "active")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_stack(project_dir: Path) -> str:
    if (project_dir / "pyproject.toml").exists() or (project_dir / "setup.py").exists():
        return "Python"
    if (project_dir / "package.json").exists():
        return "Node.js"
    if (project_dir / "Cargo.toml").exists():
        return "Rust"
    if (project_dir / "go.mod").exists():
        return "Go"
    if (project_dir / "Gemfile").exists():
        return "Ruby"
    return "unknown"
