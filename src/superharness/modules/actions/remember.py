"""Remember module actions — auto-refresh context from CLAUDE.md and last handoff."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def refresh_context(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Refresh context from CLAUDE.md, contract, and last handoff.

    This action is typically fired on `on_continue` lifecycle hook to help
    agents remember project context and previous work.

    Args:
        context: Context dict with project_dir, task_id, actor
        settings: Module settings (unused for remember module)

    Returns:
        Result dict with success status and what was refreshed
    """
    project_dir = Path(context.get("project_dir", ".")).resolve()
    task_id = context.get("task_id", "unknown")

    refreshed = {
        "claude_md": False,
        "contract": False,
        "last_handoff": False,
    }

    # 1. Read CLAUDE.md
    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        try:
            content = claude_md.read_text(encoding="utf-8")
            logger.info(f"Refreshed context from CLAUDE.md ({len(content)} bytes)")
            refreshed["claude_md"] = True
        except Exception as e:
            logger.warning(f"Failed to read CLAUDE.md: {e}")
    else:
        logger.debug("No CLAUDE.md found in project directory")

    # 2. Read contract state from SQLite
    try:
        from superharness.engine import state_reader as _sr
        doc = _sr.get_contract_doc(str(project_dir))
        if doc is not None:
            task_count = len(doc.get("tasks") or [])
            logger.info(f"Refreshed context from state.db ({task_count} tasks)")
            refreshed["contract"] = True
        else:
            logger.debug("No contract state found in state.db")
    except Exception as e:
        logger.warning(f"Failed to read contract from state.db: {e}")

    # 3. Read last handoff (most recent handoff file)
    handoffs_dir = project_dir / ".superharness" / "handoffs"
    if handoffs_dir.exists():
        # Get all handoff files, sorted by name (which includes timestamp)
        handoff_files = sorted(handoffs_dir.glob("*.md"), reverse=True)
        if handoff_files:
            last_handoff = handoff_files[0]
            try:
                content = last_handoff.read_text(encoding="utf-8")
                logger.info(
                    f"Refreshed context from last handoff {last_handoff.name} "
                    f"({len(content)} bytes)"
                )
                refreshed["last_handoff"] = True
            except Exception as e:
                logger.warning(f"Failed to read last handoff: {e}")
        else:
            logger.debug("No handoff files found")
    else:
        logger.debug("No handoffs directory found")

    return {
        "success": True,
        "context_refreshed": refreshed,
        "message": f"Context refreshed for {task_id}",
    }
