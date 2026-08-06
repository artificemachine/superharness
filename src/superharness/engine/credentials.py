"""Machine-level credential file primitives shared by integrations.

Credentials live outside project state in ``~/.config/superharness`` and are
written with owner-only permissions. ``SUPERHARNESS_CREDENTIALS_FILE`` lets
tests and isolated installations avoid the real machine credential file.
"""

from __future__ import annotations

import logging
import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path

logger = logging.getLogger(__name__)

_CREDENTIALS_PATH = Path.home() / ".config" / "superharness" / "credentials.env"


def credentials_path() -> Path:
    """Return the machine credential path, honoring the test override."""
    override = os.environ.get("SUPERHARNESS_CREDENTIALS_FILE")
    if override:
        return Path(override)
    return _CREDENTIALS_PATH


def read_credentials_file(path: Path | None = None) -> dict[str, str]:
    """Parse simple ``KEY=VALUE`` entries, ignoring comments and bad lines."""
    target = path or credentials_path()
    values: dict[str, str] = {}
    if not target.exists():
        return values
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        logger.warning("credentials: could not read credential file %s", target)
    return values


def write_credentials_file(
    updates: Mapping[str, str], path: Path | None = None
) -> None:
    """Merge entries into the credential file and enforce mode ``0600``."""
    target = path or credentials_path()
    if target.is_symlink():
        raise OSError(f"refusing to write credentials through symbolic link: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    preserved: list[str] = []
    managed = set(updates)
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                preserved.append(line)
                continue
            key = stripped.split("=", 1)[0].strip()
            if key not in managed:
                preserved.append(line)
    appended = [f"{key}={value}" for key, value in updates.items()]
    payload = "\n".join(preserved + appended) + "\n"
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    replaced = False
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        replaced = True
    finally:
        if fd >= 0:
            os.close(fd)
        if not replaced:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.warning("credentials: could not remove temporary file %s", temporary)


def get_credential(name: str, default: str = "") -> str:
    """Return a file value, then an environment fallback, then ``default``."""
    values = read_credentials_file()
    return values.get(name, os.environ.get(name, default))
