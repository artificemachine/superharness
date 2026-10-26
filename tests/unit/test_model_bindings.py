"""Tests for superharness's model bindings file model (engine/model_bindings.py)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from superharness.engine.model_bindings import (
    load_bindings,
    provider_ladder,
    stale_providers,
)

_BINDINGS = """schema: 2
tiers: [bulk, default, escalate-1, escalate-2, final-review]
providers:
  fresh-provider:
    verified: 2026-10-24
  old-provider:
    verified: 2026-10-01
harnesses:
  codex-cli:
    default_provider: fresh-provider
    bindings:
      fresh-provider:
        bulk:
          id: ladder-bulk
        default:
          id: ladder-default
        escalate-1:
          id: ladder-escalate
        escalate-2:
          id: ladder-escalate-2
      old-provider:
        default:
          id: other-provider-default
  pi:
    default_provider: old-provider
    bindings:
      old-provider:
        default:
          id: pi-default
  opencode:
    default_provider: unverified-provider
    bindings:
      unverified-provider:
        default:
          id: opencode-default
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "model-bindings.yaml"
    path.write_text(text)
    return path


def test_load_reports_missing_file(tmp_path: Path) -> None:
    """An absent file is reported as missing, never raised."""
    bindings = load_bindings(tmp_path / "absent.yaml")

    assert bindings.status == "missing"
    assert bindings.data == {}


@pytest.mark.parametrize(
    ("text", "reason_fragment"),
    [
        ("schema: 1\nharnesses: {}\n", "schema"),
        ("schema: 2\nharnesses: [unclosed\n", "YAML"),
        ("- just\n- a list\n", "mapping"),
    ],
)
def test_load_rejects_wrong_schema(tmp_path: Path, text: str, reason_fragment: str) -> None:
    """A wrong schema, unreadable YAML or a non-mapping document is invalid, with a reason."""
    bindings = load_bindings(_write(tmp_path, text))

    assert bindings.status == "invalid"
    assert reason_fragment in bindings.reason
    assert bindings.data == {}


def test_ladder_orders_higher_tiers_then_lower(tmp_path: Path) -> None:
    """The bound model comes first, then higher tiers, then lower ones, in one provider only."""
    bindings = load_bindings(_write(tmp_path, _BINDINGS))

    assert bindings.status == "ok"
    assert provider_ladder(bindings, "codex-cli", "default") == [
        "ladder-default",
        "ladder-escalate",
        "ladder-escalate-2",
        "ladder-bulk",
    ]
    assert provider_ladder(bindings, "codex-cli", "final-review") == []
    assert provider_ladder(bindings, "gemini-cli", "default") == []


def test_stale_providers_uses_review_after_days(tmp_path: Path) -> None:
    """Bound providers older than review_after_days (default 5) or never verified are stale."""
    bindings = load_bindings(_write(tmp_path, _BINDINGS))

    assert stale_providers(bindings, date(2026, 10, 26)) == [
        "old-provider",
        "unverified-provider",
    ]

    stricter = load_bindings(_write(tmp_path, "review_after_days: 1\n" + _BINDINGS))
    assert stale_providers(stricter, date(2026, 10, 26)) == [
        "fresh-provider",
        "old-provider",
        "unverified-provider",
    ]
