"""Gateway wizard section — pick a notification backend and event list.

Three outbound backends (mutually exclusive picks during onboarding):
  - relay (SSH)  — preferred; secrets live on the relay, not on this machine
  - telegram     — direct Telegram bot; bot token on this machine
  - ntfy         — ntfy.sh push notifications; self-hosted or public server

All backends write credentials to ~/.config/superharness/credentials.env
(0600, machine-level). Project-level profile.yaml only stores the events
checklist and a non-sensitive `backend` field for display.

Inbound commands (e.g. /approve via chat) are NOT enabled by Phase 1.
See docs/gateway-security.md for the threat model.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from superharness.ui.prompts import (
    print_header,
    print_info,
    print_warning,
)

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
# profile.yaml helpers (events + backend label only — no secrets)
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


def _save_events(project_dir: Path, events: list[str], backend: str) -> None:
    profile = _load_profile(project_dir)
    gateway_block = profile.get("gateway", {})
    if not isinstance(gateway_block, dict):
        gateway_block = {}
    gateway_block["events"] = list(events)
    gateway_block["backend"] = backend  # informational, no secrets
    profile["gateway"] = gateway_block
    _save_profile(project_dir, profile)


# ---------------------------------------------------------------------------
# Public API — relay backend (kept for backward compat with existing callers)
# ---------------------------------------------------------------------------

def setup_gateway(
    project_dir: Path,
    relay_ssh_host: str,
    relay_token: str,
    events: list[str],
    *,
    relay_dest: str = "telegram",
) -> None:
    """Persist relay-backend configuration."""
    from superharness.engine.relay_client import save_credentials
    save_credentials(relay_ssh_host, relay_token, relay_dest)
    _save_events(project_dir, events, backend="relay")


def setup_telegram_direct(
    project_dir: Path,
    bot_token: str,
    chat_id: str,
    events: list[str],
) -> None:
    """Persist direct-bot configuration."""
    from superharness.engine.relay_client import save_telegram_credentials
    save_telegram_credentials(bot_token, chat_id)
    _save_events(project_dir, events, backend="telegram")


def setup_ntfy(
    project_dir: Path,
    ntfy_topic: str,
    ntfy_server: str,
    events: list[str],
) -> None:
    """Persist ntfy.sh configuration."""
    from superharness.engine.relay_client import save_ntfy_credentials
    save_ntfy_credentials(ntfy_topic, ntfy_server)
    _save_events(project_dir, events, backend="ntfy")


# ---------------------------------------------------------------------------
# Onboard section entry point
# ---------------------------------------------------------------------------

_BACKEND_CHOICES = [
    ("relay",    "Relay (SSH) — secrets stay on the relay, not on this machine"),
    ("telegram", "Telegram bot — direct bot token stored on this machine"),
    ("ntfy",     "ntfy.sh — push notifications (self-hosted or ntfy.sh public)"),
    ("skip",     "Skip — no notifications"),
]


def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Gateway section: pick backend, configure credentials, pick events."""
    print_header("Notifications (gateway)")

    from superharness.engine.relay_client import (
        credentials_path,
        load_credentials,
        load_telegram_credentials,
        load_ntfy_credentials,
    )
    relay_creds = load_credentials()
    bot_creds = load_telegram_credentials()
    ntfy_creds = load_ntfy_credentials()

    profile = _load_profile(project_dir)
    gateway_cfg = profile.get("gateway", {}) or {}
    current_events: list[str] = gateway_cfg.get("events", [])
    if not isinstance(current_events, list):
        current_events = []
    current_backend: str = gateway_cfg.get("backend", "")

    if non_interactive:
        _show_current(current_backend, relay_creds, bot_creds, current_events, ntfy_creds)
        return

    print_info("Outbound notifications only. Inbound chat commands are disabled in this phase.")
    print_info("See docs/gateway-security.md for the threat model.")
    print_info(f"Credentials saved to: {credentials_path()} (mode 0600)")
    print_info("")

    from superharness.ui.prompts import prompt, prompt_choice, prompt_yes_no

    # --- Backend selection ---
    default_idx = 0  # relay first
    if current_backend == "telegram":
        default_idx = 1
    elif current_backend == "" and not relay_creds["relay_token"]:
        default_idx = 0  # still recommend relay
    backend_idx = prompt_choice(
        "Notification backend",
        [label for _, label in _BACKEND_CHOICES],
        default=default_idx,
    )
    backend_key = _BACKEND_CHOICES[backend_idx][0]

    if backend_key == "skip":
        _save_events(project_dir, [], backend="none")
        print_info("Gateway disabled.")
        return

    if backend_key == "relay":
        _configure_relay(project_dir, relay_creds, current_events)
    elif backend_key == "telegram":
        _configure_telegram_direct(project_dir, bot_creds, current_events)
    else:
        from superharness.engine.relay_client import load_ntfy_credentials
        ntfy_creds = load_ntfy_credentials()
        _configure_ntfy(project_dir, ntfy_creds, current_events)


# ---------------------------------------------------------------------------
# Relay configuration flow
# ---------------------------------------------------------------------------

def _configure_relay(project_dir: Path, current: dict, current_events: list[str]) -> None:
    from superharness.ui.prompts import prompt, prompt_yes_no

    if current["relay_ssh_host"] and current["relay_token"]:
        suffix = current["relay_token"][-6:] if len(current["relay_token"]) > 6 else "***"
        print_info(f"Already configured — host: {current['relay_ssh_host']}  token: ...{suffix}")
        if not prompt_yes_no("Reconfigure?", default=False):
            events = _pick_events(current_events)
            from superharness.engine.relay_client import save_credentials
            save_credentials(
                current["relay_ssh_host"],
                current["relay_token"],
                current.get("relay_dest") or "telegram",
            )
            _save_events(project_dir, events, backend="relay")
            return

    print_info("Uses your ~/.ssh/config alias — no user@host needed.")
    ssh_host = prompt(
        "Relay SSH alias from ~/.ssh/config",
        default=current["relay_ssh_host"],
    ).strip()
    if not ssh_host:
        print_info("No SSH host entered — gateway section skipped.")
        return

    token = prompt(
        "Relay bearer token",
        default=current["relay_token"],
    ).strip()
    if not token:
        print_info("No token entered — gateway section skipped.")
        return

    events = _pick_events(current_events)
    setup_gateway(project_dir, ssh_host, token, events)
    _summary_relay(ssh_host, token, events)


# ---------------------------------------------------------------------------
# Direct Telegram bot configuration flow
# ---------------------------------------------------------------------------

def _configure_telegram_direct(project_dir: Path, current: dict, current_events: list[str]) -> None:
    from superharness.ui.prompts import prompt, prompt_yes_no

    if current["bot_token"] and current["chat_id"]:
        suffix = current["bot_token"][-6:] if len(current["bot_token"]) > 6 else "***"
        print_info(f"Already configured — chat_id: {current['chat_id']}  token: ...{suffix}")
        if not prompt_yes_no("Reconfigure?", default=False):
            events = _pick_events(current_events)
            from superharness.engine.relay_client import save_telegram_credentials
            save_telegram_credentials(current["bot_token"], current["chat_id"])
            _save_events(project_dir, events, backend="telegram")
            return

    print_warning("Direct bot keeps the Telegram token on this machine.")
    print_warning("If possible, use the relay backend instead (no token stored locally).")
    print_info("Create a bot via @BotFather in Telegram, then send it /start from your account.")
    print_info("")

    bot_token = prompt(
        "Telegram bot token",
        default=current["bot_token"],
    ).strip()
    if not bot_token:
        print_info("No bot token entered — gateway section skipped.")
        return

    chat_id = prompt(
        "Your Telegram chat / user id (numeric)",
        default=current["chat_id"],
    ).strip()
    if not chat_id:
        print_info("No chat id entered — gateway section skipped.")
        return

    events = _pick_events(current_events)
    setup_telegram_direct(project_dir, bot_token, chat_id, events)
    _summary_telegram(bot_token, chat_id, events)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _pick_events(current: list[str]) -> list[str]:
    from superharness.ui.prompts import prompt_yes_no
    print_info("")
    print_info("Select events to receive notifications for:")
    selected: list[str] = []
    for event in ALL_GATEWAY_EVENTS:
        default_on = (event in current) if current else True
        if prompt_yes_no(f"  Notify on {event}?", default=default_on):
            selected.append(event)
    return selected


def _summary_relay(ssh_host: str, token: str, events: list[str]) -> None:
    suffix = token[-6:] if len(token) > 6 else "***"
    print_info("")
    print_info("Gateway configured (backend: relay).")
    print_info(f"  Relay host: {ssh_host}")
    print_info(f"  Token:      ...{suffix}")
    print_info(f"  Events:     {', '.join(events) or '(none)'}")


def _summary_telegram(bot_token: str, chat_id: str, events: list[str]) -> None:
    suffix = bot_token[-6:] if len(bot_token) > 6 else "***"
    print_info("")
    print_info("Gateway configured (backend: telegram).")
    print_info(f"  Chat id: {chat_id}")
    print_info(f"  Token:   ...{suffix}")
    print_info(f"  Events:  {', '.join(events) or '(none)'}")


# ---------------------------------------------------------------------------
# ntfy.sh configuration flow
# ---------------------------------------------------------------------------

def _configure_ntfy(project_dir: Path, current: dict, current_events: list[str]) -> None:
    from superharness.ui.prompts import prompt, prompt_yes_no

    if current["ntfy_topic"]:
        print_info(f"Already configured — server: {current['ntfy_server']}  topic: {current['ntfy_topic']}")
        if not prompt_yes_no("Reconfigure?", default=False):
            events = _pick_events(current_events)
            from superharness.engine.relay_client import save_ntfy_credentials
            save_ntfy_credentials(current["ntfy_topic"], current["ntfy_server"])
            _save_events(project_dir, events, backend="ntfy")
            return

    print_info("ntfy.sh sends push notifications to any device with the ntfy app.")
    print_info("Self-hosted is recommended. Leave server blank to use the public ntfy.sh.")
    print_info("")

    ntfy_server = prompt(
        "ntfy server URL (leave blank for https://ntfy.sh)",
        default=current["ntfy_server"] if current["ntfy_server"] != "https://ntfy.sh" else "",
    ).strip() or "https://ntfy.sh"

    ntfy_topic = prompt(
        "ntfy topic (unique string — keep it secret on public servers)",
        default=current["ntfy_topic"],
    ).strip()
    if not ntfy_topic:
        print_info("No topic entered — gateway section skipped.")
        return

    events = _pick_events(current_events)
    setup_ntfy(project_dir, ntfy_topic, ntfy_server, events)
    _summary_ntfy(ntfy_topic, ntfy_server, events)


def _summary_ntfy(ntfy_topic: str, ntfy_server: str, events: list[str]) -> None:
    print_info("")
    print_info("Gateway configured (backend: ntfy).")
    print_info(f"  Server: {ntfy_server}")
    print_info(f"  Topic:  {ntfy_topic}")
    print_info(f"  Events: {', '.join(events) or '(none)'}")


def _show_current(
    backend: str, relay: dict, bot: dict, events: list[str], ntfy: dict | None = None
) -> None:
    if backend == "relay" and relay["relay_token"] and relay["relay_ssh_host"]:
        suffix = relay["relay_token"][-6:] if len(relay["relay_token"]) > 6 else "***"
        print_info("Backend:   relay")
        print_info(f"Host:      {relay['relay_ssh_host']}")
        print_info(f"Token:     configured (...{suffix})")
    elif backend == "telegram" and bot["bot_token"] and bot["chat_id"]:
        suffix = bot["bot_token"][-6:] if len(bot["bot_token"]) > 6 else "***"
        print_info("Backend:   telegram (direct)")
        print_info(f"Chat id:   {bot['chat_id']}")
        print_info(f"Token:     configured (...{suffix})")
    elif backend == "ntfy" and ntfy and ntfy.get("ntfy_topic"):
        print_info("Backend:   ntfy")
        print_info(f"Server:    {ntfy['ntfy_server']}")
        print_info(f"Topic:     {ntfy['ntfy_topic']}")
    else:
        print_info("Gateway not configured.")
        print_info("Run 'shux onboard --section gateway' in an interactive terminal.")
        return
    print_info(f"Events:    {', '.join(events) or '(none)'}")
