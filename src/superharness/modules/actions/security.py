"""Security module actions — run shipguard SAST on verify."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def detect_security_scanner() -> str | None:
    """Detect available security scanner binary.

    Returns:
        Scanner name if found, None otherwise
    """
    # Check for shipguard first (preferred)
    if shutil.which("shipguard"):
        return "shipguard"

    # Check for gitleaks as fallback
    if shutil.which("gitleaks"):
        return "gitleaks"

    return None


def security_scan(context: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Run security scan (shipguard SAST) on verify.

    Args:
        context: Context dict with task_id, project_dir
        settings: Module settings with severity_threshold

    Returns:
        Result dict with success status and scan details
    """
    # Get project directory
    project_dir = context.get("project_dir", ".")
    project_path = Path(project_dir).expanduser()

    if not project_path.exists():
        logger.warning(f"Project directory does not exist: {project_path}")
        return {
            "success": False,
            "error": f"Project not found: {project_path}",
        }

    # Check if scanner is available
    scanner = detect_security_scanner()
    if not scanner:
        logger.debug("No security scanner found (shipguard/gitleaks), skipping scan")
        return {
            "success": False,
            "message": "No security scanner found",
            "skipped": True,
        }

    # Get severity threshold
    severity_threshold = settings.get("severity_threshold", "high")

    # Run shipguard scan
    try:
        logger.info(f"Running {scanner} scan on {project_path}")

        cmd = [scanner, "scan", str(project_path)]

        result = subprocess.run(
            cmd,
            cwd=project_path,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        scan_output = result.stdout + result.stderr

        # Check for critical findings
        # shipguard returns non-zero exit code when findings exist
        if result.returncode != 0:
            # Check if output contains CRITICAL findings
            if "CRITICAL" in scan_output or "HIGH" in scan_output:
                logger.warning(f"Security scan found critical issues:\n{scan_output}")
                return {
                    "success": False,
                    "blocked": True,
                    "scan_output": scan_output,
                    "message": f"{scanner} found critical security issues",
                }

            # Non-critical findings or other errors
            logger.info(f"Security scan completed with findings:\n{scan_output}")
            return {
                "success": True,
                "scan_output": scan_output,
                "message": f"{scanner} scan completed with findings",
            }

        # Clean scan
        logger.info("Security scan passed: no critical findings")
        return {
            "success": True,
            "scan_output": scan_output,
            "message": f"{scanner} scan passed",
        }

    except subprocess.TimeoutExpired:
        logger.error("Security scan timed out after 300 seconds")
        return {
            "success": False,
            "error": "Scan timeout",
        }

    except Exception as e:
        logger.error(f"Security scan failed: {e}")
        return {
            "success": False,
            "error": str(e),
        }
