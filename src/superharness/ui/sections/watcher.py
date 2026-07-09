"""Watcher section — platform-aware service installation and backend recording."""
from __future__ import annotations

import platform
from pathlib import Path

from superharness.engine.profile import read_field, write_field
from superharness.ui.prompts import print_header, print_info, print_warning


def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Show watcher status and offer platform-appropriate installation."""
    print_header("Watcher daemon")

    current_backend = read_field(project_dir, "watcher_backend")
    detected = _detect_backend()

    if current_backend:
        print_info(f"Current backend: {current_backend}")
    print_info(f"Detected platform: {platform.system()} → {detected}")

    if detected == "launchd":
        _offer_launchd(project_dir, non_interactive)
    elif detected == "systemd":
        _offer_systemd(project_dir, non_interactive)
    else:
        _offer_manual(project_dir, non_interactive)

    # Always record the detected backend for future reference
    write_field(project_dir, "watcher_backend", detected)


# ---------------------------------------------------------------------------
# Platform helpers
# ---------------------------------------------------------------------------

def _detect_backend() -> str:
    """Return 'launchd', 'systemd', or 'foreground' based on the host OS."""
    system = platform.system()
    if system == "Darwin":
        return "launchd"
    if system == "Linux":
        return "systemd"
    return "foreground"


def _offer_launchd(project_dir: Path, non_interactive: bool) -> None:
    """macOS: offer to install via launchd watchdog plist."""
    print_info("macOS launchd available — the watcher can be installed as a login item.")
    print_info("It will restart automatically if it crashes.")

    if non_interactive:
        print_info("Run 'shux operator start --port 8787' to start manually,")
        print_info("or 'shux operator install' to register as a launchd service.")
        return

    from superharness.ui.prompts import prompt_yes_no
    if prompt_yes_no("Install watcher as launchd login item?", default=False):
        try:
            from superharness.engine.launchd_health import write_watchdog_plist, bootstrap
            plist_path = write_watchdog_plist()
            ok = bootstrap(plist_path)
            if ok:
                print_info(f"Watchdog plist installed and bootstrapped: {plist_path}")
            else:
                print_warning("launchd bootstrap returned non-zero — check Console.app for errors.")
                print_info("You can retry with: shux operator start --port 8787")
        except Exception as exc:
            print_warning(f"Could not install launchd service: {exc}")
            print_info("Fallback: shux operator start --port 8787")
    else:
        print_info("Skipped launchd install. Run manually: shux operator start --port 8787")


def _offer_systemd(project_dir: Path, non_interactive: bool) -> None:
    """Linux: generate a user systemd service unit."""
    unit_dir  = Path.home() / ".config" / "systemd" / "user"
    unit_file = unit_dir / "superharness-operator.service"

    import sys
    python_bin = sys.executable
    unit_content = (
        "[Unit]\n"
        "Description=superharness operator watcher\n"
        "After=default.target\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={python_bin} -m superharness operator start --port 8787\n"
        "Restart=on-failure\n"
        "RestartSec=10\n\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )

    print_info(f"systemd user unit: {unit_file}")
    print_info("Enable with:")
    print_info("  systemctl --user enable --now superharness-operator.service")

    if non_interactive:
        print_info("Non-interactive mode — writing unit file automatically.")
        _write_unit(unit_dir, unit_file, unit_content)
        return

    from superharness.ui.prompts import prompt_yes_no
    if prompt_yes_no(f"Write systemd unit to {unit_file}?", default=True):
        _write_unit(unit_dir, unit_file, unit_content)
        print_info("Unit written. Run the enable command above to activate.")
    else:
        print_info("Skipped. Run 'shux operator start --port 8787' to start manually.")


def _write_unit(unit_dir: Path, unit_file: Path, content: str) -> None:
    try:
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_file.write_text(content, encoding="utf-8")
    except Exception as exc:
        print_warning(f"Could not write unit file: {exc}")


def _offer_manual(project_dir: Path, non_interactive: bool) -> None:
    """Other platforms: print a manual start hint."""
    print_info("Automatic service installation is not supported on this platform.")
    print_info("Start the watcher manually:")
    print_info("  shux operator start --port 8787")
    print_info("Or keep it running in a terminal with:")
    print_info("  shux watch")
