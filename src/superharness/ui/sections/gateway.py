"""Gateway wizard section — claw-relay connection + event checklist.

Credentials (relay SSH host + bearer token) are stored at machine level in
~/.config/superharness/credentials.env (mode 0600), never in any project's
.superharness/ directory.

Per-project config (profile.yaml gateway block):
    gateway.events      — which lifecycle events trigger notifications
    gateway.backend     — relay backend name (informational, default: claw-relay)
"""
from __future__ import annotations

import yaml
from pathlib import Path

from superharness.ui.prompts import print_header, print_info, print_warning

# ---------------------------------------------------------------------------
# Event catalogue
# ---------------------------------------------------------------------------

ALL_GATEWAY_EVENTS: list[str] = [
    "plan_proposed",
    "plan_approved",
    "report_ready",
    "task_failed",
    "task_closed",
]


# ---------------------------------------------------------------------------
# profile.yaml helpers (events only — no secrets)
# ---------------------------------------------------------------------------

def _load_profile(project_dir: Path) -> dict:
    profile_file = project_dir / ".superharness" / "profile.yaml"
    if not profile_file.exists():
        return {}
    try:
        doc = yaml.safe_load(profile_file.read_text(encoding="utf-8")) or {}
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _save_profile(project_dir: Path, doc: dict) -> None:
    sh = project_dir / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    (sh / "profile.yaml").write_text(
        yaml.dump(doc, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_gateway(
    project_dir: Path,
    relay_ssh_host: str,
    relay_token: str,
    events: list[str],
    *,
    relay_dest: str = "telegram",
) -> None:
    """Persist gateway configuration.

    - relay credentials  → ~/.config/superharness/credentials.env (0600, machine-level)
    - events checklist   → .superharness/profile.yaml (project-level, no secrets)
    """
    from superharness.engine.relay_client import save_credentials
    save_credentials(relay_ssh_host, relay_token, relay_dest)

    profile = _load_profile(project_dir)
    gateway_block = profile.get("gateway", {})
    if not isinstance(gateway_block, dict):
        gateway_block = {}
    gateway_block["events"] = list(events)
    gateway_block["backend"] = "claw-relay"
    profile["gateway"] = gateway_block
    _save_profile(project_dir, profile)


# ---------------------------------------------------------------------------
# Onboard section entry point
# ---------------------------------------------------------------------------

def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Gateway section: configure claw-relay for operator notifications."""
    print_header("Notifications (gateway)")

    from superharness.engine.relay_client import load_credentials, credentials_path
    creds = load_credentials()
    current_ssh_host: str = creds["relay_ssh_host"]
    current_token: str = creds["relay_token"]

    profile = _load_profile(project_dir)
    gateway_cfg = profile.get("gateway", {}) or {}
    current_events: list[str] = gateway_cfg.get("events", [])
    if not isinstance(current_events, list):
        current_events = []

    if non_interactive:
        _show_current(current_ssh_host, current_token, current_events)
        return

    print_info("Route operator notifications through claw-relay (no bot token stored locally).")
    print_info("Uses your ~/.ssh/config alias — no user@host needed.")
    print_info(f"Credentials saved to: {credentials_path()}")
    print_info("")

    from superharness.ui.prompts import prompt, prompt_yes_no

    if current_ssh_host and current_token:
        suffix = current_token[-6:] if len(current_token) > 6 else "***"
        print_info(f"Already configured — host: {current_ssh_host}  token: ...{suffix}")
        if not prompt_yes_no("Reconfigure?", default=False):
            return

    # --- Relay SSH host ---
    ssh_host = prompt(
        "Relay SSH alias from ~/.ssh/config (e.g. claw-relay)",
        default=current_ssh_host,
    ).strip()

    if not ssh_host:
        print_info("No SSH host entered — gateway section skipped.")
        print_info("Run 'shux onboard --section gateway' later to configure.")
        return

    # --- Bearer token ---
    token = prompt(
        "claw-relay bearer token",
        default=current_token,
    ).strip()

    if not token:
        print_info("No token entered — gateway section skipped.")
        return

    # --- Event checklist ---
    print_info("")
    print_info("Select events to receive notifications for:")
    selected_events: list[str] = []
    for event in ALL_GATEWAY_EVENTS:
        default_on = (event in current_events) if current_events else True
        if prompt_yes_no(f"  Notify on {event}?", default=default_on):
            selected_events.append(event)

    # --- Persist ---
    setup_gateway(project_dir, ssh_host, token, selected_events)

    print_info("")
    suffix = token[-6:] if len(token) > 6 else "***"
    print_info("Gateway configured.")
    print_info(f"  Relay host: {ssh_host}")
    print_info(f"  Token:      ...{suffix}")
    print_info(f"  Events:     {', '.join(selected_events) or '(none)'}")
    print_info(f"  Stored at:  {credentials_path()} (mode 0600)")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _show_current(ssh_host: str, token: str, events: list[str]) -> None:
    if ssh_host and token:
        suffix = token[-6:] if len(token) > 6 else "***"
        print_info(f"Relay host: {ssh_host}")
        print_info(f"Token:      configured (...{suffix})")
        print_info(f"Events:     {', '.join(events) or '(none)'}")
    else:
        print_info("Gateway not configured.")
        print_info("Run 'shux onboard --section gateway' in an interactive terminal.")
