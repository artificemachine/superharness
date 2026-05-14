"""Outbound notification dispatch — relay backend and direct Telegram bot backend.

All credentials live in ~/.config/superharness/credentials.env (machine-level,
mode 0600) — never in any project's .superharness/ directory. See
docs/gateway-security.md for the threat model that motivates this split.

Credential keys (any subset may be present):
    SUPERHARNESS_RELAY_SSH_HOST       — SSH config alias (e.g. mybox)
    SUPERHARNESS_RELAY_TOKEN          — relay bearer token
    SUPERHARNESS_RELAY_DEST           — relay destination name (default: telegram)

    SUPERHARNESS_TELEGRAM_BOT_TOKEN   — direct Telegram bot token
    SUPERHARNESS_TELEGRAM_CHAT_ID     — chat / user id to receive notifications

Public API:
    relay_is_configured() / send_via_relay(text)
    telegram_is_configured() / send_via_telegram_direct(text)
    send_notification(text)           — tries relay first, then direct bot
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credentials file helpers
# ---------------------------------------------------------------------------

_CREDENTIALS_PATH = Path.home() / ".config" / "superharness" / "credentials.env"


def credentials_path() -> Path:
    """Return machine-level credentials file path (overridable via env for tests)."""
    override = os.environ.get("SUPERHARNESS_CREDENTIALS_FILE")
    if override:
        return Path(override)
    return _CREDENTIALS_PATH


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines from *path* (ignores comments / blanks / malformed)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            out[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        logger.warning("relay_client: could not read credentials file %s", path)
    return out


def _write_env_file_merge(path: Path, updates: dict[str, str]) -> None:
    """Merge *updates* into *path* (preserves unrelated keys + comments). Mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    preserved: list[str] = []
    managed = set(updates.keys())
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                preserved.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key not in managed:
                preserved.append(line)
    appended = [f"{k}={v}" for k, v in updates.items()]
    path.write_text("\n".join(preserved + appended) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


# ----- Relay backend -------------------------------------------------------

def load_credentials() -> dict[str, str]:
    """Load relay credentials (file + env-var fallback)."""
    env = _read_env_file(credentials_path())
    return {
        "relay_token": env.get("SUPERHARNESS_RELAY_TOKEN",
                               os.environ.get("SUPERHARNESS_RELAY_TOKEN", "")),
        "relay_ssh_host": env.get("SUPERHARNESS_RELAY_SSH_HOST",
                                  os.environ.get("SUPERHARNESS_RELAY_SSH_HOST", "")),
        "relay_dest": env.get("SUPERHARNESS_RELAY_DEST",
                              os.environ.get("SUPERHARNESS_RELAY_DEST", "telegram")),
    }


def save_credentials(relay_ssh_host: str, relay_token: str, relay_dest: str = "telegram") -> None:
    """Persist relay credentials (mode 0600). Merges with existing file content."""
    _write_env_file_merge(credentials_path(), {
        "SUPERHARNESS_RELAY_SSH_HOST": relay_ssh_host,
        "SUPERHARNESS_RELAY_TOKEN": relay_token,
        "SUPERHARNESS_RELAY_DEST": relay_dest,
    })


def is_configured() -> bool:
    """Return True iff relay backend has both SSH host and token."""
    c = load_credentials()
    return bool(c["relay_token"] and c["relay_ssh_host"])


relay_is_configured = is_configured  # alias for the dual-backend API


# ----- Direct Telegram bot backend -----------------------------------------

def load_telegram_credentials() -> dict[str, str]:
    """Load direct-bot credentials (file + env-var fallback)."""
    env = _read_env_file(credentials_path())
    return {
        "bot_token": env.get("SUPERHARNESS_TELEGRAM_BOT_TOKEN",
                             os.environ.get("SUPERHARNESS_TELEGRAM_BOT_TOKEN", "")),
        "chat_id":   env.get("SUPERHARNESS_TELEGRAM_CHAT_ID",
                             os.environ.get("SUPERHARNESS_TELEGRAM_CHAT_ID", "")),
    }


def save_telegram_credentials(bot_token: str, chat_id: str) -> None:
    """Persist direct-bot credentials (mode 0600)."""
    _write_env_file_merge(credentials_path(), {
        "SUPERHARNESS_TELEGRAM_BOT_TOKEN": bot_token,
        "SUPERHARNESS_TELEGRAM_CHAT_ID": chat_id,
    })


def telegram_is_configured() -> bool:
    """Return True iff direct-bot backend has both bot token and chat id."""
    c = load_telegram_credentials()
    return bool(c["bot_token"] and c["chat_id"])


# ----- ntfy.sh backend -----------------------------------------------------

def load_ntfy_credentials() -> dict[str, str]:
    """Load ntfy.sh credentials (file + env-var fallback)."""
    env = _read_env_file(credentials_path())
    return {
        "ntfy_topic": env.get("SUPERHARNESS_NTFY_TOPIC",
                              os.environ.get("SUPERHARNESS_NTFY_TOPIC", "")),
        "ntfy_server": env.get("SUPERHARNESS_NTFY_SERVER",
                               os.environ.get("SUPERHARNESS_NTFY_SERVER", "https://ntfy.sh")),
    }


def save_ntfy_credentials(ntfy_topic: str, ntfy_server: str = "https://ntfy.sh") -> None:
    """Persist ntfy.sh credentials (mode 0600)."""
    _write_env_file_merge(credentials_path(), {
        "SUPERHARNESS_NTFY_TOPIC": ntfy_topic,
        "SUPERHARNESS_NTFY_SERVER": ntfy_server,
    })


def ntfy_is_configured() -> bool:
    """Return True iff ntfy.sh backend has a topic configured."""
    c = load_ntfy_credentials()
    return bool(c["ntfy_topic"])


# ---------------------------------------------------------------------------
# Outbound notification
# ---------------------------------------------------------------------------

def send_notification(
    text: str,
    *,
    relay_token: str = "",
    relay_ssh_host: str = "",
    relay_dest: str = "telegram",
    timeout: int = 15,
) -> bool:
    """Send *text* to *relay_dest* via the relay's outbound endpoint.

    Executes: ssh <relay_ssh_host> curl -sf POST http://localhost:7077/outbound/<dest>
    Payload is piped via stdin to avoid any shell quoting issues.

    Returns True on success (exit 0), False otherwise.
    """
    if not relay_token or not relay_ssh_host:
        logger.debug("relay_client.send_notification: no credentials — skipped")
        return False

    if not shutil.which("ssh"):
        logger.warning("relay_client: ssh not found — cannot send notification")
        return False

    payload = json.dumps({"text": text})
    remote_cmd = (
        f"curl -sf -X POST http://localhost:7077/outbound/{relay_dest}"
        f" -H 'Authorization: Bearer {relay_token}'"
        f" -H 'Content-Type: application/json'"
        f" --data-binary @-"
    )
    cmd = [
        "ssh",
        "-o", "ConnectTimeout=5",
        relay_ssh_host,
        remote_cmd,
    ]

    try:
        result = subprocess.run(
            cmd,
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            logger.warning(
                "relay_client: send failed (rc=%d): %s",
                result.returncode,
                result.stderr.decode("utf-8", errors="replace").strip(),
            )
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("relay_client: send timed out after %ds", timeout)
        return False
    except OSError as exc:
        logger.warning("relay_client: ssh exec failed: %s", exc)
        return False


def send_notification_from_config(text: str) -> bool:
    """Convenience wrapper: loads credentials automatically then sends via relay."""
    creds = load_credentials()
    return send_notification(
        text,
        relay_token=creds["relay_token"],
        relay_ssh_host=creds["relay_ssh_host"],
        relay_dest=creds["relay_dest"],
    )


# ---------------------------------------------------------------------------
# Direct Telegram bot — fallback when no relay is configured
# ---------------------------------------------------------------------------

def send_via_telegram_direct(
    text: str,
    *,
    bot_token: str = "",
    chat_id: str = "",
    timeout: int = 10,
) -> bool:
    """Send *text* via the Telegram Bot API directly (no relay).

    Used only when the relay backend is not configured. The bot token must
    live in ~/.config/superharness/credentials.env (machine-level, 0600).
    """
    if not bot_token or not chat_id:
        return False
    try:
        import urllib.parse
        import urllib.request
    except ImportError:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001 — network failure is opaque, log and move on
        logger.warning("telegram direct: send failed: %s", exc)
        return False


def send_via_telegram_direct_from_config(text: str) -> bool:
    """Convenience wrapper: loads direct-bot credentials and sends."""
    c = load_telegram_credentials()
    return send_via_telegram_direct(text, bot_token=c["bot_token"], chat_id=c["chat_id"])


# ---------------------------------------------------------------------------
# ntfy.sh backend — self-hostable, no third-party dependency
# ---------------------------------------------------------------------------

def send_via_ntfy(
    text: str,
    *,
    ntfy_topic: str = "",
    ntfy_server: str = "https://ntfy.sh",
    timeout: int = 10,
) -> bool:
    """Send *text* via ntfy.sh (or a self-hosted ntfy server).

    POST /<topic> with plaintext body. No extra dependencies beyond stdlib.
    """
    if not ntfy_topic:
        return False
    try:
        import urllib.request
    except ImportError:
        return False

    url = f"{ntfy_server.rstrip('/')}/{ntfy_topic}"
    req = urllib.request.Request(url, data=text.encode("utf-8"), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception as exc:  # noqa: BLE001
        logger.warning("ntfy: send failed: %s", exc)
        return False


def send_via_ntfy_from_config(text: str) -> bool:
    """Convenience wrapper: loads ntfy credentials and sends."""
    c = load_ntfy_credentials()
    return send_via_ntfy(text, ntfy_topic=c["ntfy_topic"], ntfy_server=c["ntfy_server"])


# ---------------------------------------------------------------------------
# Unified dispatch — relay → telegram → ntfy (priority order)
# ---------------------------------------------------------------------------

def dispatch_notification(text: str) -> tuple[bool, str]:
    """Try every configured backend in priority order, falling through on failure.

    Operator alerts are higher value than dedup — if a backend is configured
    but the send fails, still try the next. The cost of a rare double-deliver
    is much lower than the cost of a silently dropped alert.

    Returns (sent, backend_name). backend_name is one of:
      "relay"    — sent via SSH-exec to a remote relay
      "telegram" — sent via direct Telegram Bot API
      "ntfy"     — sent via ntfy.sh (self-hosted or public)
      ""         — nothing configured or all backends failed
    """
    if relay_is_configured() and send_notification_from_config(text):
        return True, "relay"
    if telegram_is_configured() and send_via_telegram_direct_from_config(text):
        return True, "telegram"
    if ntfy_is_configured() and send_via_ntfy_from_config(text):
        return True, "ntfy"
    return False, ""


# ---------------------------------------------------------------------------
# Inbound inbox read (for relay-based gateway listener)
# ---------------------------------------------------------------------------

def read_inbox(
    *,
    relay_token: str = "",
    relay_ssh_host: str = "",
    peek: bool = False,
    timeout: int = 10,
) -> list[dict]:
    """Read messages from the relay's inbox via SSH exec.

    Returns a list of message dicts, or [] on error.
    """
    if not relay_token or not relay_ssh_host:
        return []
    if not shutil.which("ssh"):
        return []

    peek_param = "?peek=true" if peek else ""
    remote_cmd = (
        f"curl -sf http://localhost:7077/inbox{peek_param}"
        f" -H 'Authorization: Bearer {relay_token}'"
    )
    cmd = [
        "ssh",
        "-o", "ConnectTimeout=5",
        relay_ssh_host,
        remote_cmd,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout.decode("utf-8"))
        messages = data if isinstance(data, list) else data.get("messages", [])
        return messages if isinstance(messages, list) else []
    except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
        return []
