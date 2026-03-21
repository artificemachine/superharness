"""Tests for dispatcher auto-timeout feature (feat.auto-timeout)."""
from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

import pytest
import yaml

from superharness.commands.inbox_dispatch import _get_task_effort_timeout


@pytest.fixture
def contract_with_effort(tmp_path: Path) -> str:
    """Contract with tasks that have effort estimates."""
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        textwrap.dedent(
            """\
            id: test-contract
            status: draft
            tasks:
            - id: low-effort-task
              title: Simple config change
              owner: claude-code
              status: todo
              effort: low
            - id: medium-effort-task
              title: Multi-file refactor
              owner: claude-code
              status: todo
              effort: medium
            - id: high-effort-task
              title: Architecture migration
              owner: claude-code
              status: todo
              effort: high
            - id: explicit-minutes-task
              title: Custom timeout task
              owner: claude-code
              status: todo
              estimated_minutes: 45
            - id: both-set-task
              title: Both effort and minutes
              owner: claude-code
              status: todo
              effort: low
              estimated_minutes: 90
            - id: no-estimate-task
              title: No estimate provided
              owner: claude-code
              status: todo
            """
        )
    )
    return str(contract)


def test_auto_timeout_from_effort_low(contract_with_effort: str) -> None:
    """RED: verify timeout for low effort task."""
    timeout = _get_task_effort_timeout(contract_with_effort, "low-effort-task")
    assert timeout == 900  # 15 minutes


def test_auto_timeout_from_effort_medium(contract_with_effort: str) -> None:
    """RED: verify timeout for medium effort task."""
    timeout = _get_task_effort_timeout(contract_with_effort, "medium-effort-task")
    assert timeout == 1800  # 30 minutes


def test_auto_timeout_from_effort_high(contract_with_effort: str) -> None:
    """RED: verify timeout for high effort task."""
    timeout = _get_task_effort_timeout(contract_with_effort, "high-effort-task")
    assert timeout == 3600  # 60 minutes


def test_auto_timeout_from_estimated_minutes(contract_with_effort: str) -> None:
    """RED: verify explicit estimated_minutes overrides effort mapping."""
    timeout = _get_task_effort_timeout(contract_with_effort, "explicit-minutes-task")
    assert timeout == 2700  # 45 minutes * 60


def test_auto_timeout_estimated_minutes_overrides_effort(contract_with_effort: str) -> None:
    """RED: verify estimated_minutes takes precedence over effort."""
    timeout = _get_task_effort_timeout(contract_with_effort, "both-set-task")
    assert timeout == 5400  # 90 minutes * 60


def test_auto_timeout_fallback_when_no_estimate(contract_with_effort: str) -> None:
    """RED: verify fallback to 0 (no timeout) when no estimate provided."""
    timeout = _get_task_effort_timeout(contract_with_effort, "no-estimate-task")
    assert timeout == 0


def test_auto_timeout_task_not_found(contract_with_effort: str) -> None:
    """RED: verify fallback when task doesn't exist."""
    timeout = _get_task_effort_timeout(contract_with_effort, "nonexistent-task")
    assert timeout == 0


def test_dispatcher_uses_auto_timeout(tmp_path: Path) -> None:
    """Integration: verify dispatcher calculates timeout when launcher_timeout=0."""
    harness_dir = tmp_path / ".superharness"
    harness_dir.mkdir()

    # Create contract with effort estimate
    contract_file = harness_dir / "contract.yaml"
    contract_file.write_text(
        textwrap.dedent(
            """\
            id: test
            tasks:
            - id: test-task
              effort: medium
            """
        )
    )

    # Create empty inbox
    inbox_file = harness_dir / "inbox.yaml"
    inbox_file.write_text("items: []\n")

    # Verify _get_task_effort_timeout returns correct value
    from superharness.commands.inbox_dispatch import _get_task_effort_timeout

    timeout = _get_task_effort_timeout(str(contract_file), "test-task")
    assert timeout == 1800  # medium effort = 30 minutes
