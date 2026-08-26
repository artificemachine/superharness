"""Regression tests: every agent allow-list must contain all canonical agents.

The canonical agent set is defined once here. Every module that maintains its
own copy is tested against it. If a new agent is added to CANONICAL_AGENTS,
each test below will immediately fail for any module not yet updated — that is
the intended behaviour.

Behavioural tests also confirm that each gate actually *accepts* every
canonical agent at runtime, not just that the constant is correct.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Ground truth — update this set when a new agent is introduced.
# Every other constant in the codebase must be a superset of this.
# ---------------------------------------------------------------------------
CANONICAL_AGENTS: frozenset[str] = frozenset(
    {
        "claude-code",
        "codex-cli",
        "gemini-cli",
        "opencode",
        "pi",
    }
)


def test_pi_is_canonical():
    """Pi is a canonical executable agent once its harness is registered."""
    assert "pi" in CANONICAL_AGENTS


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _missing(actual: set[str]) -> set[str]:
    """Return CANONICAL_AGENTS members absent from *actual*."""
    return CANONICAL_AGENTS - actual


# ===========================================================================
# Static allow-list completeness
# ===========================================================================


class TestStaticAllowLists:
    """Each module's hardcoded agent set must contain all CANONICAL_AGENTS."""

    def test_inbox_enqueue_valid_targets(self):
        from superharness.commands.inbox_enqueue import VALID_TARGETS

        missing = _missing(set(VALID_TARGETS))
        assert not missing, (
            f"inbox_enqueue.VALID_TARGETS is missing: {missing}. "
            "Add them to VALID_TARGETS on line 26."
        )

    def test_handoff_write_valid_from(self):
        from superharness.commands.handoff_write import VALID_FROM

        # owner is allowed in addition to agents — subtract it before checking
        agents_only = set(VALID_FROM) - {"owner"}
        missing = _missing(agents_only)
        assert not missing, f"handoff_write.VALID_FROM is missing: {missing}."

    def test_handoff_write_valid_to(self):
        from superharness.commands.handoff_write import VALID_TO

        agents_only = set(VALID_TO) - {"owner"}
        missing = _missing(agents_only)
        assert not missing, f"handoff_write.VALID_TO is missing: {missing}."

    def test_task_valid_owners(self):
        from superharness.commands.task import VALID_OWNERS

        agents_only = set(VALID_OWNERS) - {"owner"}
        missing = _missing(agents_only)
        assert not missing, f"task.VALID_OWNERS is missing: {missing}."

    def test_dashboard_ui_known_agents(self):
        # dashboard-ui.py has a hyphen — not importable; scan source text instead.
        src = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "superharness"
            / "scripts"
            / "dashboard-ui.py"
        )
        text = src.read_text(encoding="utf-8")
        assert "from superharness.harnesses import KNOWN_HARNESSES" in text
        assert "KNOWN_AGENTS: tuple[str, ...] = tuple(sorted(KNOWN_HARNESSES))" in text
        from superharness.harnesses import KNOWN_HARNESSES

        found = set(KNOWN_HARNESSES)
        missing = _missing(found)
        assert not missing, f"dashboard-ui.py KNOWN_AGENTS is missing: {missing}."

    def test_dashboard_wizard_all_agents(self):
        from superharness.commands.dashboard_wizard import _AGENT_LABELS, _ALL_AGENTS
        from superharness.harnesses import KNOWN_HARNESSES

        missing = _missing(set(_ALL_AGENTS))
        assert not missing, f"dashboard_wizard._ALL_AGENTS is missing: {missing}."
        assert _ALL_AGENTS == KNOWN_HARNESSES
        assert set(_AGENT_LABELS) == set(_ALL_AGENTS)
        assert "prime-agent" not in _ALL_AGENTS

    def test_ui_sections_agent_choices(self):
        from superharness.ui.sections.agent import _AGENT_CHOICES
        from superharness.harnesses import KNOWN_HARNESSES

        missing = _missing(set(_AGENT_CHOICES))
        assert not missing, (
            f"ui/sections/agent.py _AGENT_CHOICES is missing: {missing}."
        )
        assert _AGENT_CHOICES == KNOWN_HARNESSES
        assert "prime-agent" not in _AGENT_CHOICES


# ===========================================================================
# dashboard.html selector contract (text scan — not importable)
# ===========================================================================


def _read_dashboard_html() -> str:
    html = (
        Path(__file__).resolve().parent.parent.parent
        / "src"
        / "superharness"
        / "scripts"
        / "dashboard.html"
    )
    return html.read_text(encoding="utf-8")


def test_dashboard_html_uses_backend_agent_list():
    """Selectors take their choices from the executable-agent API payload."""
    html = _read_dashboard_html()
    assert re.search(
        r"KNOWN_AGENTS\s*=\s*Array\.isArray\(d\.all_task_owners\)"
        r"\s*\?\s*d\.all_task_owners\s*:\s*\[\]",
        html,
    )


def test_dashboard_html_empty_backend_agents_fallback():
    """An empty or absent backend list leaves selectors safe to render."""
    html = _read_dashboard_html()
    assert "let KNOWN_AGENTS = [];" in html
    assert "KNOWN_AGENTS[0] || ''" in html


# ===========================================================================
# inbox_watch validation tuple (text scan — tuple is inline, not a constant)
# ===========================================================================


class TestInboxWatchValidation:
    """Watcher target validation must derive from the canonical harness registry."""

    def _read_source(self) -> str:
        src = (
            Path(__file__).resolve().parent.parent.parent
            / "src"
            / "superharness"
            / "commands"
            / "inbox_watch.py"
        )
        return src.read_text(encoding="utf-8")

    def test_cli_target_validation_tuple(self):
        src = self._read_source()
        assert "from superharness.harnesses import KNOWN_HARNESSES" in src
        assert 'valid_targets = ["both", *KNOWN_HARNESSES]' in src
        from superharness.harnesses import KNOWN_HARNESSES

        found = set(KNOWN_HARNESSES)
        missing = _missing(found)
        assert not missing, (
            f"inbox_watch.py --to validation tuple is missing: {missing}. "
            "Update the opts.target check and error message."
        )

    def test_fallback_targets_list(self):
        from superharness.commands.inbox_watch import _watcher_targets

        found = set(_watcher_targets("both"))
        missing = _missing(found)
        assert not missing, (
            f"inbox_watch.py fallback targets list is missing: {missing}."
        )


# ===========================================================================
# Behavioural: each gate actually accepts every canonical agent at runtime
# ===========================================================================


class TestBehaviouralAcceptance:
    """Each validation gate must not raise or abort for any canonical agent."""

    @pytest.fixture()
    def project(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import tasks_dao
        from superharness.engine.tasks_dao import TaskRow

        conn = get_connection(str(tmp_path))
        init_db(conn)
        conn.execute("PRAGMA foreign_keys = OFF")
        for agent in CANONICAL_AGENTS:
            tasks_dao.upsert(
                conn,
                TaskRow(
                    id=f"t-{agent}",
                    title=f"task for {agent}",
                    owner=agent,
                    status="todo",
                    effort=None,
                    project_path=str(tmp_path),
                    development_method=None,
                    acceptance_criteria=[],
                    test_types=[],
                    out_of_scope=[],
                    definition_of_done=[],
                    context=None,
                    tdd=None,
                    version=1,
                    created_at="2026-01-01T00:00:00Z",
                ),
            )
        conn.commit()
        conn.close()
        return tmp_path

    @pytest.mark.parametrize("agent", sorted(CANONICAL_AGENTS))
    def test_inbox_enqueue_accepts_agent(self, agent, project):
        """inbox_enqueue must not abort for any canonical agent."""
        from superharness.commands.inbox_enqueue import VALID_TARGETS

        assert agent in VALID_TARGETS, (
            f"inbox_enqueue.VALID_TARGETS rejects '{agent}' — add it to VALID_TARGETS."
        )

    @pytest.mark.parametrize("agent", sorted(CANONICAL_AGENTS))
    def test_task_create_accepts_owner(self, agent):
        """task.VALID_OWNERS must accept every canonical agent as owner."""
        from superharness.commands.task import VALID_OWNERS

        assert agent in VALID_OWNERS, f"task.VALID_OWNERS rejects '{agent}' as owner."

    @pytest.mark.parametrize("agent", sorted(CANONICAL_AGENTS))
    def test_handoff_write_accepts_from(self, agent):
        from superharness.commands.handoff_write import VALID_FROM

        assert agent in VALID_FROM, f"handoff_write.VALID_FROM rejects '{agent}'."

    @pytest.mark.parametrize("agent", sorted(CANONICAL_AGENTS))
    def test_handoff_write_accepts_to(self, agent):
        from superharness.commands.handoff_write import VALID_TO

        assert agent in VALID_TO, f"handoff_write.VALID_TO rejects '{agent}'."

    @pytest.mark.parametrize("agent", sorted(CANONICAL_AGENTS))
    def test_enqueue_cli_end_to_end(self, agent, project):
        """inbox_enqueue CLI must accept --to <agent> without aborting."""
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "superharness.commands.inbox_enqueue",
                "--project",
                str(project),
                "--task",
                f"t-{agent}",
                "--to",
                agent,
                "--priority",
                "1",
            ],
            capture_output=True,
            text=True,
        )
        # Exit code 2 = argparse/validation abort.
        # Other non-zero codes (e.g. watcher not running) are acceptable.
        assert result.returncode != 2, (
            f"inbox_enqueue rejected agent '{agent}' with exit code 2.\n"
            f"stderr: {result.stderr.strip()}"
        )
        assert "--to must be one of" not in result.stderr, (
            f"inbox_enqueue printed allow-list error for '{agent}':\n"
            f"{result.stderr.strip()}"
        )
