"""Guard: no hardcoded claude-opus-4-N literals outside approved files.

This test enforces the single-source-of-truth contract: the flagship model
id is defined in adapter_manifests/claude-code.yaml and accessed via
adapter_registry.flagship(). Any literal ``claude-opus-4-<digit>`` string
in source (outside the approved set below) means a consumer bypassed the
registry — which is exactly the pattern that makes model bumps a 26-file
change instead of a 1-file change.

Approved files (may contain literal opus ids):
  - adapter_manifests/claude-code.yaml         — the source of truth
  - engine/adapter_registry.py                 — the resolver itself
  - engine/sdk_runner.py                        — pricing table (multi-version)
  - engine/models.yaml                          — per-project pricing overrides
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_SRC_ROOT = Path(__file__).parents[2] / "src" / "superharness"

_APPROVED_SUFFIXES = frozenset({
    "adapter_manifests/claude-code.yaml",
    "engine/adapter_registry.py",
    "engine/sdk_runner.py",
    "engine/models.yaml",
})

_LITERAL_PATTERN = re.compile(r"claude-opus-4-\d")


def _posix_rel(path: Path) -> str:
    """Return a forward-slash relative path regardless of OS."""
    return path.relative_to(_SRC_ROOT).as_posix()


def _scan() -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    for path in _SRC_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts:
            continue
        if path.suffix not in {".py", ".yaml", ".yml"}:
            continue
        rel = _posix_rel(path)
        if rel in _APPROVED_SUFFIXES:
            continue
        try:
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _LITERAL_PATTERN.search(line):
                    violations.append((rel, lineno, line.strip()))
        except (UnicodeDecodeError, OSError):
            pass
    return violations


class TestFlagshipSourceOfTruth:
    """Enforce that flagship model ids are not hardcoded outside approved files."""

    def test_flagship_resolves_from_manifest(self):
        """flagship() must return a non-empty model id string."""
        from superharness.engine.adapter_registry import flagship
        result = flagship()
        assert isinstance(result, str)
        assert result.startswith("claude-opus-")

    def test_flagship_1m_resolves_from_manifest(self):
        """flagship_1m() must return a non-empty model id string ending with [1m]."""
        from superharness.engine.adapter_registry import flagship_1m
        result = flagship_1m()
        assert isinstance(result, str)
        assert "[1m]" in result

    def test_fallback_flagship_resolves_from_manifest(self):
        """fallback_flagship() must return a non-empty model id string."""
        from superharness.engine.adapter_registry import fallback_flagship
        result = fallback_flagship()
        assert isinstance(result, str)
        assert result.startswith("claude-opus-")

    def test_flagship_differs_from_fallback(self):
        """flagship and fallback must be different versions."""
        from superharness.engine.adapter_registry import fallback_flagship, flagship
        assert flagship() != fallback_flagship()

    def test_no_hardcoded_opus_literals_outside_approved_files(self):
        """No claude-opus-4-N literal may appear outside the approved file list.

        Failure means a consumer bypassed adapter_registry — fix it by importing
        flagship() / fallback_flagship() / flagship_1m() instead.
        """
        violations = _scan()
        if violations:
            lines = [f"  {rel}:{lineno}  {snippet}" for rel, lineno, snippet in violations]
            pytest.fail(
                "Hardcoded claude-opus-4-N literals found outside approved files.\n"
                "Fix: import flagship() from superharness.engine.adapter_registry instead.\n\n"
                + "\n".join(lines)
            )
