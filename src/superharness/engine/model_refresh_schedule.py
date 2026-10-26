"""Daily scheduler for `shux models refresh`.

Renders, installs and uninstalls a launchd agent that runs the installed
`shux models refresh` once a day. Rendering is pure; every host change goes
through ``_run`` so tests replace it. Install and uninstall are inverse:
uninstall removes the plist and the log files the scheduler wrote.

The scheduler must run the installed `shux`, never a checkout: a `shux`
inside a git work tree is refused, because switching or deleting that
checkout would change or break what the scheduler runs.

AACP registration precedes any real install on a managed host; this module
never registers anything.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LABEL = "com.superharness.models-refresh"
DEFAULT_HOUR = 9
DEFAULT_MINUTE = 17
_SYSTEM_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


class ScheduleError(Exception):
    """A refusal or a failed host command; the CLI prints it and exits 1."""


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _platform() -> str:
    return sys.platform


def _uid() -> int:
    return os.getuid()


@dataclass(frozen=True)
class LaunchdPaths:
    home: Path

    @property
    def agents_dir(self) -> Path:
        return self.home / "Library" / "LaunchAgents"

    @property
    def plist(self) -> Path:
        return self.agents_dir / f"{LABEL}.plist"

    @property
    def log_dir(self) -> Path:
        return self.home / "Library" / "Logs" / "superharness"

    @property
    def logs(self) -> tuple[Path, Path]:
        return (self.log_dir / f"{LABEL}.out.log", self.log_dir / f"{LABEL}.err.log")


def _inside_git_checkout(path: Path) -> Path | None:
    for parent in path.parents:
        if (parent / ".git").exists():
            return parent
    return None


def resolve_installed_shux() -> Path:
    """The absolute `shux` on PATH; refuse one that lives in a git checkout."""
    found = _which("shux")
    if not found:
        raise ScheduleError("no installed `shux` on PATH; install superharness first")
    shux = Path(found).absolute()
    for candidate in (shux, shux.resolve()):
        checkout = _inside_git_checkout(candidate)
        if checkout is not None:
            raise ScheduleError(
                f"refusing {candidate}: it is inside the git checkout {checkout}. "
                "The scheduler must run an installed copy (pipx or a wheel), never a checkout."
            )
    return shux


def launchd_plist(shux: Path, *, hour: int, minute: int, log_dir: Path) -> str:
    """The launchd agent that runs `<shux> models refresh` daily at hour:minute."""
    out_log, err_log = log_dir / f"{LABEL}.out.log", log_dir / f"{LABEL}.err.log"
    document = {
        "Label": LABEL,
        "ProgramArguments": [str(shux), "models", "refresh"],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": False,
        "EnvironmentVariables": {"PATH": f"{shux.parent}:{_SYSTEM_PATH}"},
        "StandardOutPath": str(out_log),
        "StandardErrorPath": str(err_log),
    }
    return plistlib.dumps(document).decode("utf-8")


def _loaded() -> bool:
    return _run(["launchctl", "print", f"gui/{_uid()}/{LABEL}"]).returncode == 0


def _check(result: subprocess.CompletedProcess, what: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise ScheduleError(f"{what} failed: {detail}")


def install_commands(paths: LaunchdPaths) -> list[list[str]]:
    return [["launchctl", "bootstrap", f"gui/{_uid()}", str(paths.plist)]]


def uninstall_commands() -> list[list[str]]:
    return [["launchctl", "bootout", f"gui/{_uid()}/{LABEL}"]]


def install(paths: LaunchdPaths, text: str) -> None:
    """Write the plist and load it; on a load failure remove the plist again."""
    if _loaded():
        raise ScheduleError(f"{LABEL} is already loaded; run `shux models schedule uninstall --apply` first")
    paths.log_dir.mkdir(parents=True, exist_ok=True)
    paths.agents_dir.mkdir(parents=True, exist_ok=True)
    paths.plist.write_text(text, encoding="utf-8")
    try:
        for cmd in install_commands(paths):
            _check(_run(cmd), " ".join(cmd[:2]))
    except ScheduleError:
        paths.plist.unlink(missing_ok=True)
        raise


def uninstall(paths: LaunchdPaths) -> list[Path]:
    """Unload the agent if loaded, then delete the plist and its logs; return what was removed."""
    if _loaded():
        for cmd in uninstall_commands():
            _check(_run(cmd), " ".join(cmd[:2]))
    removed = []
    for path in (paths.plist, *paths.logs):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def status(paths: LaunchdPaths) -> str:
    """One line: whether the plist exists and whether launchd has it loaded."""
    present, loaded = paths.plist.exists(), _loaded()
    if present and loaded:
        return f"scheduler: installed and loaded ({paths.plist})"
    if present:
        return f"scheduler: installed but not loaded ({paths.plist})"
    if loaded:
        return f"scheduler: loaded without its plist ({paths.plist} is missing)"
    return "scheduler: not installed"
