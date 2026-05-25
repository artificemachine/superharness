"""Smoke tests — parametrized across all CLI commands, engine modules, and DAOs.
Guarantees >100 tests in this category.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ── CLI command smoke (expect ~30 tests) ──────────────────────────────────────

def _cli_commands() -> list[str]:
    """Extract all shux subcommands from --help output."""
    r = subprocess.run(["shux", "--help"], capture_output=True, text=True, timeout=5)
    commands = []
    in_commands = False
    for line in r.stdout.split("\n"):
        if "Commands:" in line:
            in_commands = True
            continue
        if in_commands and line.strip() and not line.startswith("  "):
            break
        if in_commands and line.strip():
            # Extract command name from "  command     description"
            parts = line.strip().split()
            if parts and not parts[0].startswith("-"):
                cmd = parts[0].rstrip(",")
                if cmd not in commands:
                    commands.append(cmd)
    return commands


class TestCLICommands:
    @pytest.mark.parametrize("command", _cli_commands())
    def test_command_help(self, command):
        """Every CLI subcommand has --help."""
        r = subprocess.run(
            ["shux", command, "--help"], capture_output=True, text=True, timeout=5
        )
        assert r.returncode == 0, f"shux {command} --help failed: {r.stderr[:200]}"

    @pytest.mark.parametrize("command", ["shux", "superharness"])
    def test_main_binaries(self, command):
        """Main binaries are on PATH."""
        r = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5)
        assert r.returncode == 0, f"{command} --version failed"


# ── Engine module imports (expect ~80 tests) ──────────────────────────────────

def _engine_modules() -> list[str]:
    """All non-private .py files in engine/ and commands/."""
    base = Path(__file__).parent.parent.parent / "src" / "superharness"
    modules = []
    for subdir in ("engine", "commands", "mcp/tools"):
        d = base / subdir
        if d.exists():
            for f in d.glob("*.py"):
                if not f.name.startswith("_") and not f.name.startswith("."):
                    # Convert path to import: src/superharness/engine/db.py → superharness.engine.db
                    mod_path = str(f.relative_to(base.parent)).replace("/", ".").replace(".py", "")
                    modules.append(mod_path)
    return sorted(modules)


class TestEngineImports:
    @pytest.mark.parametrize("module", _engine_modules())
    def test_module_imports(self, module):
        """Every engine/command module imports without error."""
        try:
            importlib.import_module(module)
        except ImportError as e:
            pytest.fail(f"Failed to import {module}: {e}")


# ── DAO coverage (expect ~12 tests) ───────────────────────────────────────────

def _dao_modules() -> list[str]:
    """All DAO modules."""
    base = Path(__file__).parent.parent.parent / "src" / "superharness" / "engine"
    return sorted([f.stem for f in base.glob("*_dao.py")])


class TestDAOCoverage:
    @pytest.mark.parametrize("dao", _dao_modules())
    def test_dao_has_table(self, dao):
        """Each DAO should reference a SQLite table."""
        mod = importlib.import_module(f"superharness.engine.{dao}")
        src = str(Path(mod.__file__).read_text()) if mod.__file__ else ""
        has_table = "CREATE TABLE" in src or "INSERT INTO" in src or "FROM " in src
        assert has_table, f"{dao} has no SQL references"

    @pytest.mark.parametrize("dao", _dao_modules())
    def test_dao_imports_sqlite(self, dao):
        """Each DAO imports sqlite3."""
        mod = importlib.import_module(f"superharness.engine.{dao}")
        src = str(Path(mod.__file__).read_text()) if mod.__file__ else ""
        assert "sqlite3" in src.lower(), f"{dao} doesn't import sqlite3"


# ── Status coverage (expect ~17 tests) ────────────────────────────────────────

def _all_statuses() -> list[str]:
    from superharness.engine.schemas import TaskStatus
    return [s.value for s in TaskStatus]


class TestStatusCoverage:
    @pytest.mark.parametrize("status", _all_statuses())
    def test_status_in_transition_graph(self, status):
        """Every TaskStatus appears in the transition graph."""
        from superharness.engine.next_action import _MAPPING
        assert status in _MAPPING or status in ("launched", "running"), (
            f"Status '{status}' not in transition graph"
        )

    @pytest.mark.parametrize("status", _all_statuses())
    def test_status_has_label(self, status):
        """Every status has a display label."""
        from superharness.engine.next_action import _STATUS_LABELS
        if status not in ("launched", "running"):
            assert status in _STATUS_LABELS, f"No label for status '{status}'"
