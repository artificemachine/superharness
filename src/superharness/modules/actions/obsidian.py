"""Obsidian module actions — write task handoffs to Obsidian vault."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def detect_vault(vault_path: str | None = None) -> str | None:
    """Detect Obsidian vault at known paths or explicit path.

    Args:
        vault_path: Optional explicit path to check

    Returns:
        Path to vault if found, None otherwise
    """
    # If explicit path provided, check it
    if vault_path:
        vault_dir = Path(vault_path).expanduser()
        if vault_dir.exists() and (vault_dir / ".obsidian").exists():
            return str(vault_dir)
        return None

    # Known vault locations
    known_paths = [
        Path.home() / "Documents" / "OBSIDIAN_ICLOUD" / "coredev",
        Path.home() / "Documents" / "Obsidian",
        Path.home() / "Obsidian",
    ]

    for path in known_paths:
        if path.exists() and (path / ".obsidian").exists():
            return str(path)

    return None


def is_mcp_available() -> bool:
    """Check if Obsidian MCP server is available.

    Returns:
        True if MCP server is running and accessible
    """
    # TODO: Check if obsidian-semantic MCP server is callable
    # For now, return False (level 1-2 only)
    return False


def redact_secrets(text: str) -> str:
    """Redact secrets from text.

    Args:
        text: Input text potentially containing secrets

    Returns:
        Text with secrets redacted
    """
    if not text:
        return text

    # Common secret patterns
    patterns = [
        # API keys (various formats)
        (r"sk-[a-zA-Z0-9]{10,}", "[REDACTED-API-KEY]"),
        (r"api[_-]?key[:\s=]+[a-zA-Z0-9_-]{16,}", "[REDACTED-API-KEY]"),
        # GitHub tokens
        (r"ghp_[a-zA-Z0-9]{10,}", "[REDACTED-GITHUB-TOKEN]"),
        (r"gho_[a-zA-Z0-9]{10,}", "[REDACTED-GITHUB-TOKEN]"),
        (r"ghu_[a-zA-Z0-9]{10,}", "[REDACTED-GITHUB-TOKEN]"),
        (r"ghs_[a-zA-Z0-9]{10,}", "[REDACTED-GITHUB-TOKEN]"),
        # AWS keys
        (r"AKIA[0-9A-Z]{16}", "[REDACTED-AWS-KEY]"),
        # Private IPs (10.x, 172.16-31.x, 192.168.x)
        (r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[REDACTED-PRIVATE-IP]"),
        (r"\b172\.(1[6-9]|2[0-9]|3[01])\.\d{1,3}\.\d{1,3}\b", "[REDACTED-PRIVATE-IP]"),
        (r"\b192\.168\.\d{1,3}\.\d{1,3}\b", "[REDACTED-PRIVATE-IP]"),
        # Generic tokens
        (r"token[:\s=]+[a-zA-Z0-9_-]{20,}", "[REDACTED-TOKEN]"),
        (r"bearer\s+[a-zA-Z0-9_-]{20,}", "[REDACTED-BEARER-TOKEN]"),
    ]

    redacted = text
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)

    return redacted


def obsidian_write_note(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Write task handoff as Obsidian vault note.

    Args:
        context: Context dict with task_id, summary, project_name, actor
        settings: Module settings with vault_path, vault_subfolder, filename_pattern, redact_secrets

    Returns:
        Result dict with success status and note_path (if written)
    """
    # Get vault path
    vault_path_str = settings.get("vault_path")
    if not vault_path_str:
        # Try auto-detection
        vault_path_str = detect_vault()
        if not vault_path_str:
            logger.debug("No Obsidian vault found, skipping note write")
            return {
                "success": False,
                "message": "No vault found",
            }

    vault_path = Path(vault_path_str).expanduser()

    # Verify vault exists
    if not vault_path.exists():
        logger.warning(f"Vault path does not exist: {vault_path}")
        return {
            "success": False,
            "error": f"Vault not found: {vault_path}",
        }

    # Extract context
    task_id = context.get("task_id", "unknown")
    summary = context.get("summary", "")
    project_name = context.get("project_name", "unknown")
    actor = context.get("actor", "unknown")

    # Redact secrets if enabled
    redact = settings.get("redact_secrets", True)
    if redact:
        summary = redact_secrets(summary)

    # Build file path
    subfolder_pattern = settings.get("vault_subfolder", "1_ai/{project_name}/")
    subfolder = subfolder_pattern.format(project_name=project_name)

    filename_pattern = settings.get("filename_pattern", "{project_name}-{date}-{title}.md")
    date_str = datetime.now().strftime("%Y-%m-%d")

    # Generate title from task_id or summary
    title = task_id.replace(".", "-")

    filename = filename_pattern.format(
        project_name=project_name,
        date=date_str,
        title=title,
    )

    # Create full path
    note_dir = vault_path / subfolder
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / filename

    # Generate frontmatter
    frontmatter = f"""---
task_id: {task_id}
project: {project_name}
actor: {actor}
date: {date_str}
tags:
  - superharness
  - task-handoff
---

"""

    # Generate note content
    content = frontmatter + f"""# {task_id}

{summary}

---
*Generated by superharness on {date_str}*
"""

    # Write note
    try:
        note_path.write_text(content, encoding="utf-8")
        logger.info(f"Wrote Obsidian note: {note_path}")
        return {
            "success": True,
            "note_path": str(note_path),
        }
    except Exception as e:
        logger.error(f"Failed to write Obsidian note: {e}")
        return {
            "success": False,
            "error": str(e),
        }
