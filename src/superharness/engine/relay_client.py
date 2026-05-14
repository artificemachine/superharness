"""Outbound notification via claw-relay.

Sends notifications through the claw-relay webhook proxy using an SSH exec
instead of a direct HTTP connection.  The relay bearer token and SSH host live
in ~/.config/superharness/credentials.env (machine-level, mode 0600) — they
are never stored in any project's .superharness/ directory.

Credential keys expected in credentials.env:
    SUPERHARNESS_RELAY_TOKEN    — claw-relay bearer token
    SUPERHARNESS_RELAY_SSH_HOST — SSH config alias, e.g. claw-relay
    SUPERHARNESS_RELAY_DEST     — relay destination name (default: telegram)

Usage:
    from superharness.engine.relay_client import send_notification, load_credentials
    creds = load_credentials()
    ok = send_notification("task t-abc done", **creds)
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


def load_credentials() -> dict[str, str]:
    """Load relay credentials from the machine-level credentials file.

    Returns a dict with keys: relay_token, relay_ssh_host, relay_dest.
    Falls back to environment variables if the file is absent.
    """
    creds: dict[str, str] = {
        "relay_token": os.environ.get("SUPERHARNESS_RELAY_TOKEN", ""),
        "relay_ssh_host": os.environ.get("SUPERHARNESS_RELAY_SSH_HOST", ""),
        "relay_dest": os.environ.get("SUPERHARNESS_RELAY_DEST", "telegram"),
    }

    path = credentials_path()
    if not path.exists():
        return creds

    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key == "SUPERHARNESS_RELAY_TOKEN":
                creds["relay_token"] = value
            elif key == "SUPERHARNESS_RELAY_SSH_HOST":
                creds["relay_ssh_host"] = value
            elif key == "SUPERHARNESS_RELAY_DEST":
                creds["relay_dest"] = value
    except OSError:
        logger.warning("relay_client: could not read credentials file %s", path)

    return creds


def save_credentials(relay_ssh_host: str, relay_token: str, relay_dest: str = "telegram") -> None:
    """Write relay credentials to the machine-level credentials file (mode 0600).

    Merges with any existing entries — other keys are preserved.
    """
    path = credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing lines, strip keys we are about to rewrite
    existing: list[str] = []
    managed_keys = {"SUPERHARNESS_RELAY_TOKEN", "SUPERHARNESS_RELAY_SSH_HOST", "SUPERHARNESS_RELAY_DEST"}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                existing.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key not in managed_keys:
                existing.append(line)

    lines = existing + [
        f"SUPERHARNESS_RELAY_SSH_HOST={relay_ssh_host}",
        f"SUPERHARNESS_RELAY_TOKEN={relay_token}",
        f"SUPERHARNESS_RELAY_DEST={relay_dest}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def is_configured() -> bool:
    """Return True iff relay credentials are available (file or env vars)."""
    creds = load_credentials()
    return bool(creds["relay_token"] and creds["relay_ssh_host"])


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
    """Send *text* to *relay_dest* via the claw-relay outbound endpoint.

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
    """Convenience wrapper: loads credentials automatically then sends."""
    creds = load_credentials()
    return send_notification(
        text,
        relay_token=creds["relay_token"],
        relay_ssh_host=creds["relay_ssh_host"],
        relay_dest=creds["relay_dest"],
    )


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
    """Read messages from the claw-relay inbox via SSH exec.

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
