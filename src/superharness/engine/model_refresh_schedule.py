"""Daily scheduler for `shux models refresh`.

Renders, installs and uninstalls the scheduler that runs the installed
`shux models refresh` once a day: a launchd agent on macOS, a systemd user
service and timer on Linux. Windows is refused. Rendering is pure; every host
command goes through ``_run`` so tests replace it. Install and uninstall are
inverse: uninstall removes every file install wrote (and the launchd logs).

The scheduler must run the installed `shux`, never a checkout: a `shux`
inside a git work tree is refused, because switching or deleting that
checkout would change or break what the scheduler runs.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

LABEL = "com.superharness.models-refresh"
SYSTEMD_UNIT = "superharness-models-refresh"
DEFAULT_HOUR = 9
DEFAULT_MINUTE = 17
_SYSTEM_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"


class ScheduleError(Exception):
    """A refusal or a failed host command; the CLI prints it and exits 1."""


class UnsupportedPlatform(ScheduleError):
    """No scheduler backend for this platform; the CLI exits 2."""


def _which(name: str) -> str | None:
    return shutil.which(name)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _platform() -> str:
    return sys.platform


def _uid() -> int:
    return os.getuid()


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


def _search_path(shux: Path) -> str:
    return f"{shux.parent}:{_SYSTEM_PATH}"


def launchd_plist(shux: Path, *, hour: int, minute: int, log_dir: Path) -> str:
    """The launchd agent that runs `<shux> models refresh` daily at hour:minute."""
    document = {
        "Label": LABEL,
        "ProgramArguments": [str(shux), "models", "refresh"],
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": False,
        "EnvironmentVariables": {"PATH": _search_path(shux)},
        "StandardOutPath": str(log_dir / f"{LABEL}.out.log"),
        "StandardErrorPath": str(log_dir / f"{LABEL}.err.log"),
    }
    return plistlib.dumps(document).decode("utf-8")


def systemd_units(shux: Path, *, hour: int, minute: int) -> tuple[str, str]:
    """The systemd user service and timer that run `<shux> models refresh` daily; output goes to the journal."""
    service = (
        "[Unit]\n"
        "Description=superharness daily model bindings refresh\n\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={shux} models refresh\n"
        f"Environment=PATH={_search_path(shux)}\n"
    )
    timer = (
        "[Unit]\n"
        "Description=superharness daily model bindings refresh timer\n\n"
        "[Timer]\n"
        f"OnCalendar=*-*-* {hour:02d}:{minute:02d}:00\n"
        "Persistent=true\n"
        f"Unit={SYSTEMD_UNIT}.service\n\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def _check(result: subprocess.CompletedProcess, cmd: list[str]) -> None:
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise ScheduleError(f"{' '.join(cmd)} failed: {detail}")


class LaunchdBackend:
    """macOS: one agent plist under ~/Library/LaunchAgents, logs under ~/Library/Logs/superharness."""

    def __init__(self, home: Path) -> None:
        self.unit_dir = home / "Library" / "LaunchAgents"
        self.log_dir = home / "Library" / "Logs" / "superharness"
        self.plist = self.unit_dir / f"{LABEL}.plist"

    def render(self, shux: Path, hour: int, minute: int) -> dict[Path, str]:
        return {self.plist: launchd_plist(shux, hour=hour, minute=minute, log_dir=self.log_dir)}

    def files(self) -> list[Path]:
        return [self.plist]

    def extra_files(self) -> list[Path]:
        return [self.log_dir / f"{LABEL}.out.log", self.log_dir / f"{LABEL}.err.log"]

    def prepare(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def install_commands(self) -> list[list[str]]:
        return [["launchctl", "bootstrap", f"gui/{_uid()}", str(self.plist)]]

    def uninstall_commands(self) -> list[list[str]]:
        return [["launchctl", "bootout", f"gui/{_uid()}/{LABEL}"]]

    def after_removal_commands(self) -> list[list[str]]:
        return []

    def loaded(self) -> bool:
        return _run(["launchctl", "print", f"gui/{_uid()}/{LABEL}"]).returncode == 0


class SystemdBackend:
    """Linux: a user service and timer under ~/.config/systemd/user; output goes to the journal."""

    def __init__(self, home: Path) -> None:
        self.unit_dir = home / ".config" / "systemd" / "user"
        self.service = self.unit_dir / f"{SYSTEMD_UNIT}.service"
        self.timer = self.unit_dir / f"{SYSTEMD_UNIT}.timer"

    def render(self, shux: Path, hour: int, minute: int) -> dict[Path, str]:
        service, timer = systemd_units(shux, hour=hour, minute=minute)
        return {self.service: service, self.timer: timer}

    def files(self) -> list[Path]:
        return [self.service, self.timer]

    def extra_files(self) -> list[Path]:
        return []

    def prepare(self) -> None:
        return None

    def install_commands(self) -> list[list[str]]:
        return [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", "--now", self.timer.name],
        ]

    def uninstall_commands(self) -> list[list[str]]:
        return [["systemctl", "--user", "disable", "--now", self.timer.name]]

    def after_removal_commands(self) -> list[list[str]]:
        return [["systemctl", "--user", "daemon-reload"]]

    def loaded(self) -> bool:
        return _run(["systemctl", "--user", "is-enabled", self.timer.name]).returncode == 0


_BACKENDS = {"darwin": LaunchdBackend, "linux": SystemdBackend}


def backend_for(home: Path) -> LaunchdBackend | SystemdBackend:
    """The scheduler backend for this platform; Windows and others are refused."""
    platform = _platform()
    if platform.startswith(("win", "cygwin", "msys")):
        raise UnsupportedPlatform("scheduling the refresh is not supported on Windows")
    backend = _BACKENDS.get(platform)
    if backend is None:
        raise UnsupportedPlatform(f"scheduling the refresh is not supported on {platform}")
    return backend(home)


def install(backend: LaunchdBackend | SystemdBackend, files: dict[Path, str]) -> None:
    """Write the scheduler files and load them; on a load failure remove what was written."""
    if backend.loaded():
        raise ScheduleError("the refresh scheduler is already loaded; "
                            "run `shux models schedule uninstall --apply` first")
    backend.prepare()
    backend.unit_dir.mkdir(parents=True, exist_ok=True)
    written = []
    try:
        for path, text in files.items():
            path.write_text(text, encoding="utf-8")
            written.append(path)
        for cmd in backend.install_commands():
            _check(_run(cmd), cmd)
    except (ScheduleError, OSError):
        for path in written:
            path.unlink(missing_ok=True)
        raise


def uninstall(backend: LaunchdBackend | SystemdBackend) -> list[Path]:
    """Unload the scheduler if loaded, then delete its files; return what was removed."""
    if backend.loaded():
        for cmd in backend.uninstall_commands():
            _check(_run(cmd), cmd)
    removed = []
    for path in (*backend.files(), *backend.extra_files()):
        if path.exists():
            path.unlink()
            removed.append(path)
    if removed:
        for cmd in backend.after_removal_commands():
            _check(_run(cmd), cmd)
    return removed


def status(backend: LaunchdBackend | SystemdBackend) -> str:
    """One line: whether the scheduler files exist and whether the scheduler is loaded."""
    files = backend.files()
    present, loaded = all(path.exists() for path in files), backend.loaded()
    where = ", ".join(str(path) for path in files)
    if present and loaded:
        return f"scheduler: installed and loaded ({where})"
    if present:
        return f"scheduler: installed but not loaded ({where})"
    if loaded:
        return f"scheduler: loaded without its files ({where} missing)"
    return "scheduler: not installed"
