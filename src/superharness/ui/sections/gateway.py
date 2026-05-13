"""Gateway wizard section — Telegram bot token, allowlist, event checklist.

Acceptance criteria (I7):
  - setup_gateway saves token and allowlist to .superharness/watcher-env.yaml
  - setup_gateway saves events checklist to .superharness/profile.yaml
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import yaml

from superharness.ui.prompts import print_header, print_info, print_warning

# ---------------------------------------------------------------------------
# Event catalogue — all events the gateway can notify about
# ---------------------------------------------------------------------------

ALL_GATEWAY_EVENTS: list[str] = [
    "plan_proposed",
    "plan_approved",
    "report_ready",
    "task_failed",
    "task_closed",
]


# ---------------------------------------------------------------------------
# watcher-env.yaml helpers
# ---------------------------------------------------------------------------

def _load_watcher_env(project_dir: Path) -> dict:
    """Load .superharness/watcher-env.yaml; returns {} on missing/error."""
    env_file = project_dir / ".superharness" / "watcher-env.yaml"
    if not env_file.exists():
        return {}
    try:
        doc = yaml.safe_load(env_file.read_text(encoding="utf-8")) or {}
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _save_watcher_env(project_dir: Path, updates: dict[str, str]) -> None:
    """Merge *updates* into .superharness/watcher-env.yaml (mode 0600)."""
    from datetime import datetime, timezone

    sh = project_dir / ".superharness"
    sh.mkdir(parents=True, exist_ok=True)
    env_file = sh / "watcher-env.yaml"

    doc = _load_watcher_env(project_dir)
    env_block = doc.get("env", {})
    if not isinstance(env_block, dict):
        env_block = {}
    env_block.update(updates)
    doc["env"] = env_block
    doc["captured_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    env_file.write_text(yaml.dump(doc, default_flow_style=False), encoding="utf-8")
    env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


# ---------------------------------------------------------------------------
# profile.yaml helpers
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
    token: str,
    allowed_senders: list[str],
    events: list[str],
) -> None:
    """Persist gateway configuration.

    - token + allowlist  → .superharness/watcher-env.yaml (chmod 0600)
    - events             → .superharness/profile.yaml under gateway.events
    """
    # 1. Save token and allowlist to watcher-env.yaml
    _save_watcher_env(project_dir, {
        "SUPERHARNESS_TELEGRAM_BOT_TOKEN": token,
        "SUPERHARNESS_TELEGRAM_ALLOWED_SENDERS": ",".join(str(s) for s in allowed_senders),
    })

    # 2. Save events checklist to profile.yaml
    profile = _load_profile(project_dir)
    gateway_block = profile.get("gateway", {})
    if not isinstance(gateway_block, dict):
        gateway_block = {}
    gateway_block["events"] = list(events)
    profile["gateway"] = gateway_block
    _save_profile(project_dir, profile)


# ---------------------------------------------------------------------------
# Onboard section entry point
# ---------------------------------------------------------------------------

def run(project_dir: Path, non_interactive: bool = False) -> None:
    """Gateway section: configure Telegram bot for operator notifications."""
    print_header("Notifications (gateway)")

    # Read current config
    existing_doc = _load_watcher_env(project_dir)
    existing_env = existing_doc.get("env", {}) or {}
    current_token: str = existing_env.get("SUPERHARNESS_TELEGRAM_BOT_TOKEN", "")
    current_senders: str = existing_env.get("SUPERHARNESS_TELEGRAM_ALLOWED_SENDERS", "")

    profile = _load_profile(project_dir)
    gateway_cfg = profile.get("gateway", {}) or {}
    current_events: list[str] = gateway_cfg.get("events", [])
    if not isinstance(current_events, list):
        current_events = []

    if non_interactive:
        _show_current(current_token, current_senders, current_events)
        return

    # Interactive flow
    print_info("Configure a Telegram bot to receive operator notifications.")
    print_info("You need: a bot token from @BotFather and your Telegram user ID(s).")
    print_info("")

    from superharness.ui.prompts import prompt, prompt_yes_no

    if current_token:
        suffix = current_token[-6:] if len(current_token) > 6 else "***"
        print_info(f"Already configured (token ends ...{suffix})")
        if not prompt_yes_no("Reconfigure?", default=False):
            return

    # --- Bot token ---
    token = prompt(
        "Telegram bot token (from @BotFather)",
        default=current_token,
    ).strip()

    if not token:
        print_info("No token entered — gateway section skipped.")
        print_info("Run 'shux onboard --section gateway' later to configure.")
        return

    # --- Allowed senders ---
    senders_raw = prompt(
        "Allowed sender IDs (comma-separated Telegram user/chat IDs)",
        default=current_senders,
    ).strip()
    allowed_senders = [s.strip() for s in senders_raw.split(",") if s.strip()]

    if not allowed_senders:
        print_warning("No allowed senders entered — the gateway will reject all messages.")

    # --- Event checklist ---
    print_info("")
    print_info("Select events to receive notifications for:")
    selected_events: list[str] = []
    for event in ALL_GATEWAY_EVENTS:
        default_on = (event in current_events) if current_events else True
        if prompt_yes_no(f"  Notify on {event}?", default=default_on):
            selected_events.append(event)

    # --- Persist ---
    setup_gateway(project_dir, token, allowed_senders, selected_events)

    print_info("")
    suffix = token[-6:] if len(token) > 6 else "***"
    print_info(f"Gateway configured.")
    print_info(f"  Token:           ...{suffix}")
    print_info(f"  Allowed senders: {', '.join(allowed_senders) or '(none)'}")
    print_info(f"  Events:          {', '.join(selected_events) or '(none)'}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _show_current(token: str, senders: str, events: list[str]) -> None:
    if token:
        suffix = token[-6:] if len(token) > 6 else "***"
        print_info(f"Token:           configured (...{suffix})")
        print_info(f"Allowed senders: {senders or '(none)'}")
        print_info(f"Events:          {', '.join(events) or '(none)'}")
    else:
        print_info("Gateway not configured.")
        print_info("Run 'shux onboard --section gateway' in an interactive terminal.")
