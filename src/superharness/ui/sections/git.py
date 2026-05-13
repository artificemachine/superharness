"""Git & tracking section — reads/writes team_size and git_mode in profile.yaml."""
from __future__ import annotations

import subprocess
from pathlib import Path

from superharness.ui.prompts import print_header, print_info
from superharness.ui.sections.base import run_section

_TEAM_SIZE_CHOICES = ["solo", "small", "large"]
_GIT_MODE_CHOICES  = ["team", "solo"]


def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Show and optionally update git tracking settings."""
    from superharness.engine.profile import read_field

    print_header("Git & tracking")

    is_git = _is_git_repo(project_dir)
    current_team_size = read_field(project_dir, "team_size") or "solo"
    current_git_mode  = read_field(project_dir, "git_mode") or "team"

    print_info(f"Git repo:  {'yes' if is_git else 'no'}")
    print_info(f"Team size: {current_team_size}")
    print_info(f"Git mode:  {current_git_mode}")

    if not is_git:
        print_info("No git repo detected — git tracking skipped.")
        return

    # Team size
    run_section(
        project_dir,
        field="team_size",
        label="Team size",
        choices=_TEAM_SIZE_CHOICES,
        non_interactive=non_interactive,
        default_override=current_team_size,
    )

    # Git mode (team = .superharness/ committed, solo = gitignored)
    git_mode = run_section(
        project_dir,
        field="git_mode",
        label="Git mode (team=shared state, solo=local only)",
        choices=_GIT_MODE_CHOICES,
        non_interactive=non_interactive,
        default_override=current_git_mode,
    )

    # Delegate gitignore work to the existing onboard helper
    try:
        from superharness.commands.onboard import _step_git_track
        _step_git_track(project_dir, {}, git_mode)
    except Exception as exc:  # pragma: no cover
        print_info(f"Note: could not update .gitignore: {exc}")


# ---------------------------------------------------------------------------

def _is_git_repo(project_dir: Path) -> bool:
    try:
        r = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--git-dir"],
            capture_output=True,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False
