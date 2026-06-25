"""macOS launchd health and self-heal for the Superharness operator.

Three classes of divergence this module catches and repairs:

1. **Plist on disk but not loaded** — operator never auto-restarts because
   launchd doesn't know it exists. Caused by missing `launchctl bootstrap`
   after writing the plist, or by a manual `launchctl bootout`.
2. **Zombie launchd entry** — service is in `launchctl list` but the
   plist file is gone. Survives forever, accumulates after upgrades.
3. **Stale version** — service is loaded but uses an old label/pattern
   that the current install no longer ships. e.g. the legacy
   `com.superharness.inbox.worker-proj*` agents that 1.56+ doesn't use.

All operations are best-effort and degrade gracefully on non-macOS
platforms (return empty results / False).
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)


# Service-label prefixes the current superharness ships. Anything else
# under com.superharness.* is treated as a stale prior-version artifact
# and bootout'd during cleanup.
CURRENT_LABEL_PREFIXES: tuple[str, ...] = (
    "com.superharness.operator.",
    "com.superharness.operator-watchdog.",
)

# Patterns that should always be removed (legacy from pre-1.56 layouts).
STALE_LABEL_PATTERNS: tuple[str, ...] = (
    "com.superharness.inbox.",     # pre-1.50 inbox-watcher agents
    "com.superharness.watcher.",   # short-lived intermediate scheme
)


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def _launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _uid() -> int:
    # os.getuid is POSIX-only — guarded with getattr so unit tests on
    # Windows can monkey-patch platform.system() to "Darwin" without
    # the heal() code path AttributeError'ing here.
    getter = getattr(os, "getuid", None)
    return getter() if getter else 0


def _run(cmd: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LaunchdEntry:
    label: str
    pid: int | None       # None if not running
    last_exit_code: int | None


def list_loaded_superharness_services() -> list[LaunchdEntry]:
    """Return all com.superharness.* services known to launchd.

    Best-effort: on non-macOS or when launchctl is unavailable returns [].
    """
    if not _is_macos():
        return []
    try:
        result = _run(["launchctl", "list"])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []

    entries: list[LaunchdEntry] = []
    for line in result.stdout.splitlines():
        if "com.superharness." not in line:
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        pid_str, exit_str, label = parts[0], parts[1], parts[2].strip()
        pid: int | None
        try:
            pid = int(pid_str)
        except ValueError:
            pid = None
        try:
            exit_code: int | None = int(exit_str)
        except ValueError:
            exit_code = None
        entries.append(LaunchdEntry(label=label, pid=pid, last_exit_code=exit_code))
    return entries


def plist_path_for_label(label: str) -> Path:
    return _launch_agents_dir() / f"{label}.plist"


def find_zombies() -> list[LaunchdEntry]:
    """Services loaded in launchd whose plist file is missing on disk."""
    return [
        e for e in list_loaded_superharness_services()
        if not plist_path_for_label(e.label).is_file()
    ]


def find_stale_versions() -> list[LaunchdEntry]:
    """Services from prior superharness layouts that the current install
    no longer ships (e.g. com.superharness.inbox.* from pre-1.50)."""
    return [
        e for e in list_loaded_superharness_services()
        if any(e.label.startswith(p) for p in STALE_LABEL_PATTERNS)
    ]


def find_orphan_plists() -> list[Path]:
    """Plist files on disk for stale-pattern labels even if not loaded.

    These are leftovers from prior installs that should be removed so
    they don't get auto-loaded on next login.
    """
    if not _is_macos():
        return []
    dir_ = _launch_agents_dir()
    if not dir_.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(dir_.glob("com.superharness.*.plist")):
        label = p.stem
        if any(label.startswith(stale) for stale in STALE_LABEL_PATTERNS):
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def is_loaded(label: str) -> bool:
    if not _is_macos():
        return False
    try:
        result = _run(["launchctl", "list", label])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def bootout(label: str) -> bool:
    """Unload a service from launchd. Returns True on success."""
    if not _is_macos():
        return False
    try:
        result = _run(["launchctl", "bootout", f"gui/{_uid()}/{label}"])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    # bootout returns non-zero for "service not loaded" which we treat as success.
    return True


def bootstrap(plist_path: Path) -> bool:
    """Load a plist into launchd. Returns True if the service ends up
    loaded (whether by this call or already loaded)."""
    if not _is_macos() or not plist_path.is_file():
        return False
    label = plist_path.stem
    if is_loaded(label):
        return True
    try:
        _run(["launchctl", "bootstrap", f"gui/{_uid()}", str(plist_path)])
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return is_loaded(label)


# ---------------------------------------------------------------------------
# Heal — orchestrate the full self-repair pass
# ---------------------------------------------------------------------------


@dataclass
class HealReport:
    zombies_removed: list[str]
    stale_services_removed: list[str]
    orphan_plists_removed: list[str]
    bootstrapped: list[str]
    skipped_reason: str | None = None
    label: str | None = None
    project: str | None = None

    def summary(self) -> str:
        if self.skipped_reason:
            return f"launchd-heal: skipped ({self.skipped_reason})"
        parts = []
        if self.zombies_removed:
            parts.append(f"removed {len(self.zombies_removed)} zombie(s): {', '.join(self.zombies_removed)}")
        if self.stale_services_removed:
            parts.append(f"removed {len(self.stale_services_removed)} stale service(s): {', '.join(self.stale_services_removed)}")
        if self.orphan_plists_removed:
            parts.append(f"removed {len(self.orphan_plists_removed)} orphan plist(s): {', '.join(self.orphan_plists_removed)}")
        if self.bootstrapped:
            parts.append(f"bootstrapped {len(self.bootstrapped)}: {', '.join(self.bootstrapped)}")
        if not parts:
            return "launchd-heal: nothing to do (state is clean)"
        return "launchd-heal: " + "; ".join(parts)

    def fixed_count(self) -> int:
        return (
            len(self.zombies_removed)
            + len(self.stale_services_removed)
            + len(self.orphan_plists_removed)
            + len(self.bootstrapped)
        )


def heal(operator_plist: Path | None = None, *, remove_orphan_plists: bool = True) -> HealReport:
    """Run the full self-heal sequence:

    1. Bootout zombies (loaded but no plist on disk).
    2. Bootout stale-pattern services from prior layouts.
    3. Remove stale-pattern plist files (defense for next login).
    4. Bootstrap `operator_plist` if it exists and isn't loaded.

    Pass `operator_plist=None` to skip the bootstrap step (e.g. when
    called from `status --fix` and the plist hasn't been installed yet).
    """
    report = HealReport([], [], [], [])
    if not _is_macos():
        report.skipped_reason = "not macOS"
        return report

    # 1. Zombies
    for z in find_zombies():
        if bootout(z.label):
            report.zombies_removed.append(z.label)

    # 2. Stale-pattern services
    for s in find_stale_versions():
        if bootout(s.label):
            report.stale_services_removed.append(s.label)

    # 3. Orphan plists on disk for stale patterns
    if remove_orphan_plists:
        for p in find_orphan_plists():
            try:
                p.unlink()
                report.orphan_plists_removed.append(p.name)
            except OSError:
                pass

    # 4. Bootstrap the operator plist
    if operator_plist is not None and operator_plist.is_file():
        if not is_loaded(operator_plist.stem):
            if bootstrap(operator_plist):
                report.bootstrapped.append(operator_plist.stem)

    return report


# ---------------------------------------------------------------------------
# Watchdog plist — re-heals every 5 min in case the operator gets evicted
# ---------------------------------------------------------------------------


def watchdog_label() -> str:
    return "com.superharness.operator-watchdog"


def watchdog_plist_path() -> Path:
    return _launch_agents_dir() / f"{watchdog_label()}.plist"


def write_watchdog_plist(python_bin: str | None = None, interval_seconds: int = 300) -> Path:
    """Install a watchdog launchd agent that runs `shux operator heal`
    every N seconds. Default 300s = 5 min. The watchdog itself has
    KeepAlive=true so launchd will restart it if it crashes.

    The watchdog is what catches the pathological case the user hit:
    operator plist on disk + not loaded → no auto-restart possible
    without manual intervention.
    """
    if not _is_macos():
        return watchdog_plist_path()
    py = python_bin or sys.executable
    label = watchdog_label()
    log_dir = Path.home() / "Library" / "Logs" / "superharness"
    log_dir.mkdir(parents=True, exist_ok=True)
    plist_path = watchdog_plist_path()
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(_render_watchdog_plist(label, py, interval_seconds, log_dir))
    return plist_path


def _render_watchdog_plist(label: str, python_bin: str, interval: int, log_dir: Path) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>-m</string>
        <string>superharness.cli</string>
        <string>operator</string>
        <string>heal</string>
        <string>--auto-discover</string>
        <string>--quiet</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{Path.home()}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>StandardOutPath</key>
    <string>{log_dir}/{label}.out.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/{label}.err.log</string>
</dict>
</plist>
"""


PERSISTENT_MARKER = "persistent"

# macOS TCC-protected (and otherwise irrelevant) top-level home
# subdirectories that the default $HOME auto-discovery walk must not
# descend into. Walking these under an ad-hoc-signed Python interpreter
# trips the "<app> would like to access data from other apps" TCC prompt
# on every scan (every 5 min via the watchdog), and they never contain
# superharness projects. Skipping them removes the prompt loop and makes
# the scan cheaper. Only applied to the default $HOME scan — callers that
# pass search_roots explicitly are honored as-is.
# (Fix: TCC-prompt-loop-auto-discover.)
_HOME_TCC_PROTECTED_DIRNAMES = frozenset({
    "Library",
    "Desktop",
    "Documents",
    "Downloads",
    "Movies",
    "Music",
    "Pictures",
    "Applications",
    ".Trash",
})


def find_all_superharness_projects(
    search_roots: list[Path] | None = None,
    max_depth: int = 3,
    require_marker: bool = True,
) -> list[Path]:
    """Discover project directories containing a `.superharness/` directory.

    Searches `search_roots` (defaults to ``$HOME`` if not provided)
    up to `max_depth` levels deep. Returns a list of resolved project paths.

    When `require_marker` is True (the default), only projects that contain
    `.superharness/persistent` are returned. This prevents `operator install
    --all` and `heal --auto-discover` from silently enrolling every project
    that has ever been `shux init`-ed into a persistent system service.

    Create the marker with: ``touch .superharness/persistent``

    (Fix: BUGREPORT watcher-silent-death-no-recovery, root cause #4.)
    """
    _log.debug("launchd_health: scanning for .superharness/ dirs (require_marker=%s)", require_marker)
    # Default $HOME scan prunes TCC-protected home subdirs; explicit
    # search_roots are honored verbatim so callers can target them.
    default_home_scan = search_roots is None
    if search_roots is None:
        search_roots = [Path.home()]

    skip_paths: set[str] = set()
    if default_home_scan:
        home = Path.home()
        skip_paths = {os.path.join(str(home), name) for name in _HOME_TCC_PROTECTED_DIRNAMES}

    found: list[Path] = []
    seen: set[Path] = set()

    for root in search_roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, _ in os.walk(root):
            depth = len(Path(dirpath).relative_to(root).parts)
            if depth > max_depth:
                dirnames.clear()  # don't recurse deeper
                continue
            harness_dir = Path(dirpath) / ".superharness"
            if harness_dir.is_dir():
                if require_marker and not (harness_dir / PERSISTENT_MARKER).is_file():
                    _log.debug("launchd_health: skipping %s (no .superharness/persistent marker)", dirpath)
                else:
                    project = Path(dirpath).resolve()
                    if project not in seen:
                        seen.add(project)
                        found.append(project)
            # Skip hidden dirs (noise) and TCC-protected home subdirs (prompt loop).
            dirnames[:] = [
                d for d in dirnames
                if (not d.startswith(".") or d == ".superharness")
                and os.path.join(dirpath, d) not in skip_paths
            ]

    _log.debug("launchd_health: discovered %d project(s) with .superharness/", len(found))
    return found


def heal_all(search_roots: list[Path] | None = None) -> list[HealReport]:
    """Run `heal()` for every discovered project with `.superharness/`.

    Each project's operator plist is resolved via its deterministic
    label hash. Returns a list of per-project HealReports.
    """
    import hashlib

    projects = find_all_superharness_projects(search_roots=search_roots)
    reports: list[HealReport] = []
    any_fixes = False

    for project_dir in projects:
        short = hashlib.md5(str(project_dir).encode()).hexdigest()[:8]
        operator_label = f"com.superharness.operator.{short}"
        operator_plist = Path.home() / "Library" / "LaunchAgents" / f"{operator_label}.plist"

        report = heal(operator_plist=operator_plist if operator_plist.is_file() else None)
        report.label = operator_label
        report.project = str(project_dir)
        reports.append(report)
        if report.fixed_count():
            any_fixes = True

    if any_fixes:
        summary_lines = "\n".join(
            f"  [{r.label}] {r.summary()}" for r in reports if r.fixed_count()
        )
        _log.info("launchd_health: heal_all fixed %d project(s):\n%s", sum(1 for r in reports if r.fixed_count()), summary_lines)
    else:
        _log.debug("launchd_health: heal_all — nothing to fix across %d project(s)", len(projects))

    return reports
