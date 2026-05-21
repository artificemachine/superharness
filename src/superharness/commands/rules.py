"""shux rules — query project rules stored in .superharness/rules/

Rules are Markdown files with YAML frontmatter. Each rule encodes a fact
about the project that agents should know — state backend, policies,
conventions, architecture decisions.

Usage:
  shux rules                  list all rules (id, title, status)
  shux rules <id>             show full rule content
  shux rules --search <kw>    search rules by keyword in title/body
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import logging
logger = logging.getLogger(__name__)


def _parse_rule(path: Path) -> dict[str, Any] | None:
    """Parse a rule .md file with YAML frontmatter. Returns None on failure."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("rules.py unexpected error: %s", e, exc_info=True)
        return None

    # Extract YAML frontmatter between --- markers
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", text, re.DOTALL)
    if not match:
        return None

    frontmatter_text = match.group(1)
    body = match.group(2).strip()

    # Parse frontmatter as simple key: value pairs (avoid yaml dependency)
    meta: dict[str, Any] = {}
    for line in frontmatter_text.split("\n"):
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    meta["_body"] = body
    meta["_file"] = str(path)
    return meta


def _rules_dir(project_dir: str | None = None) -> Path:
    """Return the rules directory path."""
    if project_dir:
        return Path(project_dir) / ".superharness" / "rules"
    # Default: find project root from cwd or SUPERHARNESS_PROJECT
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".superharness").is_dir():
            return parent / ".superharness" / "rules"
    return cwd / ".superharness" / "rules"


def list_rules(project_dir: str | None = None) -> list[dict[str, Any]]:
    """Return all rules with metadata (no body)."""
    rules_dir = _rules_dir(project_dir)
    if not rules_dir.is_dir():
        return []

    rules = []
    for f in sorted(rules_dir.glob("*.md")):
        rule = _parse_rule(f)
        if rule:
            rules.append({
                "id": rule.get("id", f.stem),
                "title": rule.get("title", f.stem),
                "status": rule.get("status", "active"),
                "since": rule.get("since", ""),
            })
    return rules


def show_rule(rule_id: str, project_dir: str | None = None) -> str | None:
    """Return the full content of a rule by id."""
    rules_dir = _rules_dir(project_dir)
    for f in sorted(rules_dir.glob("*.md")):
        rule = _parse_rule(f)
        if rule and rule.get("id") == rule_id:
            return f.read_text(encoding="utf-8")
    return None


def search_rules(keyword: str, project_dir: str | None = None) -> list[dict[str, Any]]:
    """Search rules by keyword in title or body."""
    rules_dir = _rules_dir(project_dir)
    if not rules_dir.is_dir():
        return []

    kw = keyword.lower()
    results = []
    for f in sorted(rules_dir.glob("*.md")):
        rule = _parse_rule(f)
        if not rule:
            continue
        text = (rule.get("title", "") + " " + rule.get("_body", "")).lower()
        if kw in text:
            results.append({
                "id": rule.get("id", f.stem),
                "title": rule.get("title", f.stem),
                "snippet": rule["_body"][:200] + ("..." if len(rule["_body"]) > 200 else ""),
            })
    return results


def all_rules_text(project_dir: str | None = None) -> str:
    """Return all active rules as a single text block for agent context injection."""
    rules_dir = _rules_dir(project_dir)
    if not rules_dir.is_dir():
        return ""

    parts = []
    for f in sorted(rules_dir.glob("*.md")):
        rule = _parse_rule(f)
        if rule is None:
            continue
        text = f.read_text(encoding="utf-8").strip()
        if text:
            parts.append(text)
    return "\n\n---\n\n".join(parts)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[0] in ("list", "-l", "--list"):
        rules = list_rules()
        if not rules:
            print("No rules found in .superharness/rules/")
            return
        print(f"{'ID':<30} {'STATUS':<10} TITLE")
        print("-" * 70)
        for r in rules:
            print(f"{r['id']:<30} {r['status']:<10} {r['title']}")
        return

    if argv[0] in ("--search", "-s"):
        if len(argv) < 2:
            print("Usage: shux rules --search <keyword>", file=sys.stderr)
            sys.exit(1)
        results = search_rules(argv[1])
        if not results:
            print(f"No rules matching '{argv[1]}'")
            return
        for r in results:
            print(f"\n◆ {r['id']} — {r['title']}")
            print(f"  {r['snippet']}")
        return

    # Show specific rule
    content = show_rule(argv[0])
    if content:
        print(content)
    else:
        print(f"Rule '{argv[0]}' not found", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
