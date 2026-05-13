"""audit-self — validate superharness codebase health and protocol compliance.

Verification includes:
1. SQLite-only data access: No unauthorized raw YAML reads of state files.
2. Logging compliance: Use centralized logging_utils.get_logger.
3. Changelog hygiene: Ensure CHANGELOG.md is append-only (not fully implemented).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from superharness.logging_utils import get_logger

_log = get_logger("audit-self")

# Files allowed to read state YAMLs for ingestion or export purposes
_ALLOWED_YAML_READERS = {
    "migrate_yaml.py",
    "yaml_io.py",
    "yaml_helpers.py",
    "contract_io.py",
    "state_reader.py",
    "state_writer.py",
}


def run_audit_self(project_dir: str) -> int:
    """Run codebase static analysis checks."""
    print(f"Auditing superharness codebase: {project_dir}")
    issues = 0
    src_dir = os.path.join(project_dir, "src", "superharness")

    # 1. SQLite-only data access pattern check
    print("Checking for unauthorized YAML state reads...")
    yaml_patterns = [
        r"safe_load\(.*contract\.yaml",
        r"safe_load\(.*inbox\.yaml",
        r"yaml\.safe_load\(.*contract",
        r"yaml\.safe_load\(.*inbox",
    ]
    
    for root, _, files in os.walk(src_dir):
        for file in files:
            if not file.endswith(".py") or file in _ALLOWED_YAML_READERS:
                continue
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                for pattern in yaml_patterns:
                    if re.search(pattern, content):
                        rel_path = os.path.relpath(path, project_dir)
                        print(f"  [FAIL] Unauthorized YAML read pattern '{pattern}' in {rel_path}")
                        issues += 1

    # 2. Logging compliance check
    print("Checking for logging compliance...")
    for root, _, files in os.walk(src_dir):
        for file in files:
            if not file.endswith(".py") or file == "logging_utils.py":
                continue
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                # Fail if 'import logging' is used without 'get_logger' or 'logging_utils'
                if "import logging" in content and "get_logger" not in content and "logging_utils" not in content:
                    rel_path = os.path.relpath(path, project_dir)
                    print(f"  [FAIL] Direct 'import logging' without centralized get_logger in {rel_path}")
                    issues += 1

    # 3. Changelog existence
    print("Checking CHANGELOG.md...")
    changelog = os.path.join(project_dir, "CHANGELOG.md")
    if not os.path.exists(changelog):
        print("  [FAIL] CHANGELOG.md is missing")
        issues += 1
    else:
        print("  [PASS] CHANGELOG.md exists")

    if issues > 0:
        print(f"\nAudit FAILED with {issues} issue(s).")
        return 1
    
    print("\nAudit PASSED successfully.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", nargs="?", default=".")
    args = parser.parse_args()
    sys.exit(run_audit_self(os.path.abspath(args.project)))
