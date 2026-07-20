"""Tests for shux adapter-payload --json command."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT, seed_sqlite_from_yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(args: list[str], cwd: str | None = None):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-m", "superharness.commands.adapter_payload"] + args,
        cwd=cwd or str(REPO_ROOT),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def _setup(tmp_path: Path, *, tasks: list[dict] | None = None) -> Path:
    """Create a minimal .superharness/ project under tmp_path."""
    project = tmp_path / "proj"
    sh = project / ".superharness"
    (sh / "handoffs").mkdir(parents=True)
    (sh / "failures.yaml").write_text("failures: []\n")
    (sh / "decisions.yaml").write_text("decisions: []\n")
    (sh / "inbox.yaml").write_text("# inbox\n")
    (sh / "ledger.md").write_text("# Ledger\n\n")

    raw_tasks = tasks or [
        {"id": "feat.one", "title": "Feature one", "owner": "claude-code", "status": "in_progress"},
    ]
    task_yaml = "\n".join(
        f"  - id: {t['id']}\n    title: \"{t['title']}\"\n"
        f"    owner: {t['owner']}\n    status: {t['status']}"
        + (f"\n    dependency: {t['dependency']}" if "dependency" in t else "")
        for t in raw_tasks
    )
    (sh / "contract.yaml").write_text(
        f"id: test-contract\ngoal: Test goal\ncreated: 2026-01-01\n"
        f"created_by: owner\nstatus: active\ntasks:\n{task_yaml}\n"
    )
    seed_sqlite_from_yaml(project)
    return project


# ---------------------------------------------------------------------------
# Schema structure
# ---------------------------------------------------------------------------

class TestSchema:
    def test_schema_version_is_current(self, tmp_path):
        project = _setup(tmp_path)
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        # 1.3: next_action per task added
        assert d["schema_version"] == "1.4"

    def test_top_level_keys_present(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        for key in ("schema_version", "contract_id", "goal", "tasks",
                    "edges", "ledger", "failures", "decisions", "inbox", "rules"):
            assert key in d, f"missing top-level key: {key}"

    def test_rules_field_is_list(self, tmp_path):
        project = _setup(tmp_path)
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        assert isinstance(d["rules"], list)

    def test_rules_field_includes_active_rules(self, tmp_path):
        project = _setup(tmp_path)
        rules_dir = project / ".superharness" / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        (rules_dir / "test-rule.md").write_text(
            "---\nid: test-rule\ntitle: Test Rule\nstatus: active\nsince: v1.0\n---\n\nDo not do X.\n"
        )
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        rule_ids = [r["id"] for r in d["rules"]]
        assert "test-rule" in rule_ids

    def test_contract_id_and_goal(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["contract_id"] == "test-contract"
        assert d["goal"] == "Test goal"

    def test_output_is_valid_json(self, tmp_path):
        project = _setup(tmp_path)
        r = _run(["--project", str(project)])
        assert r.returncode == 0
        json.loads(r.stdout)  # must not raise


# ---------------------------------------------------------------------------
# Task fields
# ---------------------------------------------------------------------------

class TestTaskFields:
    def test_task_required_fields(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        for f in ("id", "title", "status", "display_status", "color",
                  "owner", "blocked_by", "acceptance_criteria", "handoffs"):
            assert f in task, f"task missing field: {f}"

    def test_task_id_and_title(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert task["id"] == "feat.one"
        assert task["title"] == "Feature one"

    def test_blocked_by_is_list(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert isinstance(d["tasks"][0]["blocked_by"], list)

    def test_acceptance_criteria_is_list(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert isinstance(d["tasks"][0]["acceptance_criteria"], list)

    def test_handoffs_is_list(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert isinstance(d["tasks"][0]["handoffs"], list)


# ---------------------------------------------------------------------------
# blocked_by normalization — YAML null sentinels must collapse to []
# ---------------------------------------------------------------------------

def _write_contract(project: Path, blocked_by_literal: str) -> None:
    """Write a minimal contract.yaml with a single task carrying the given
    `blocked_by:` YAML literal (passed verbatim, so callers can test `none`,
    `null`, `~`, lists, etc.)."""
    sh = project / ".superharness"
    (sh / "handoffs").mkdir(parents=True, exist_ok=True)
    (sh / "failures.yaml").write_text("failures: []\n")
    (sh / "decisions.yaml").write_text("decisions: []\n")
    (sh / "inbox.yaml").write_text("# inbox\n")
    (sh / "ledger.md").write_text("# Ledger\n\n")
    (sh / "contract.yaml").write_text(
        "id: test-contract\ngoal: G\ncreated: 2026-01-01\n"
        "created_by: owner\nstatus: active\n"
        "tasks:\n"
        "  - id: t1\n"
        "    title: T\n"
        "    owner: claude-code\n"
        "    status: todo\n"
        f"    blocked_by: {blocked_by_literal}\n"
    )


class TestBlockedByNormalization:
    """blocked_by must collapse YAML null sentinels (none, null, ~, '') to []."""

    def _blocked_by(self, tmp_path: Path, literal: str) -> list[str]:
        project = tmp_path / f"proj_{abs(hash(literal)) % 10_000}"
        project.mkdir()
        _write_contract(project, literal)
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)["tasks"][0]["blocked_by"]

    def test_literal_none_collapses_to_empty_list(self, tmp_path):
        assert self._blocked_by(tmp_path, "none") == []

    def test_literal_null_collapses_to_empty_list(self, tmp_path):
        assert self._blocked_by(tmp_path, "null") == []

    def test_literal_tilde_collapses_to_empty_list(self, tmp_path):
        assert self._blocked_by(tmp_path, "~") == []

    def test_empty_string_collapses_to_empty_list(self, tmp_path):
        assert self._blocked_by(tmp_path, '""') == []

    def test_empty_list_collapses_to_empty_list(self, tmp_path):
        assert self._blocked_by(tmp_path, "[]") == []

    def test_scalar_task_id_preserved(self, tmp_path):
        assert self._blocked_by(tmp_path, "iter-0-red") == ["iter-0-red"]

    def test_list_filters_null_sentinels(self, tmp_path):
        assert self._blocked_by(tmp_path, "[none, iter-0, null]") == ["iter-0"]

    def test_list_of_task_ids_preserved(self, tmp_path):
        assert self._blocked_by(tmp_path, "[iter-0, iter-1]") == ["iter-0", "iter-1"]


# ---------------------------------------------------------------------------
# display_status + color mapping
# ---------------------------------------------------------------------------

class TestStatusMapping:
    _cases = [
        ("todo",             "pending",    "#6b7280"),
        ("plan_proposed",    "pending",    "#c8922a"),
        ("plan_approved",    "generating", "#4e8098"),
        ("in_progress",      "generating", "#4e8098"),
        ("report_ready",     "validating", "#8b5cf6"),
        ("review_requested", "validating", "#8b5cf6"),
        ("review_passed",    "validating", "#10b981"),
        ("review_failed",    "failed",     "#ef4444"),
        ("done",             "done",       "#10b981"),
        ("failed",           "failed",     "#ef4444"),
        ("stopped",          "failed",     "#ef4444"),
    ]

    def test_all_status_mappings(self, tmp_path):
        for raw_status, expected_display, expected_color in self._cases:
            project = _setup(tmp_path / raw_status, tasks=[
                {"id": "t1", "title": "T", "owner": "claude-code", "status": raw_status},
            ])
            d = json.loads(_run(["--project", str(project)]).stdout)
            task = d["tasks"][0]
            assert task["display_status"] == expected_display, \
                f"status={raw_status}: expected display_status={expected_display}, got {task['display_status']}"
            assert task["color"] == expected_color, \
                f"status={raw_status}: expected color={expected_color}, got {task['color']}"

    def test_unknown_status_falls_back_to_pending(self):
        """An unrecognized status should not crash the display mapping —
        falls back to pending.

        Iteration 6 of docs/PLAN-hire-ready.md (migration v35) added a
        CHECK(status IN (...ALL_STATUSES...)) constraint on tasks.status, so
        a genuinely unrecognized status like "some_future_status" can no
        longer reach tasks_dao.upsert()/the tasks table at all — the
        write is rejected with sqlite3.IntegrityError before adapter_payload
        ever sees it. That's the fix working as intended (an unrecognized
        status used to sit invisibly in the table forever; now it's rejected
        at the write boundary instead). This test now exercises
        _display_status() directly rather than round-tripping an
        unrepresentable status through YAML-seed -> SQLite -> the CLI
        subprocess, since that path is what the CHECK constraint exists to
        close.
        """
        from superharness.commands.adapter_payload import _display_status
        display, color = _display_status("some_future_status")
        assert display == "pending"


# ---------------------------------------------------------------------------
# blocked_by normalization
# ---------------------------------------------------------------------------

class TestBlockedBy:
    def test_dependency_scalar_normalized_to_list(self, tmp_path):
        """YAML `dependency: t1` must become `blocked_by: ['t1']`."""
        project = _setup(tmp_path, tasks=[
            {"id": "t1", "title": "T1", "owner": "claude-code", "status": "done"},
            {"id": "t2", "title": "T2", "owner": "claude-code", "status": "todo",
             "dependency": "t1"},
        ])
        d = json.loads(_run(["--project", str(project)]).stdout)
        t2 = next(t for t in d["tasks"] if t["id"] == "t2")
        assert t2["blocked_by"] == ["t1"]

    def test_root_task_has_empty_blocked_by(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["tasks"][0]["blocked_by"] == []


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

class TestEdges:
    def test_root_task_gets_contract_edge(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert any(
            e["source"] == "__contract__" and e["type"] == "contract"
            for e in d["edges"]
        )

    def test_dependency_produces_dependency_edge(self, tmp_path):
        project = _setup(tmp_path, tasks=[
            {"id": "t1", "title": "T1", "owner": "claude-code", "status": "done"},
            {"id": "t2", "title": "T2", "owner": "claude-code", "status": "todo",
             "dependency": "t1"},
        ])
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert any(
            e["source"] == "t1" and e["target"] == "t2" and e["type"] == "dependency"
            for e in d["edges"]
        )

    def test_edge_fields_present(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        for e in d["edges"]:
            assert "source" in e and "target" in e and "type" in e


# ---------------------------------------------------------------------------
# Handoffs
# ---------------------------------------------------------------------------

class TestHandoffs:
    def test_handoff_attached_to_correct_task(self, tmp_path):
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_handoff
        seed_sqlite_handoff(
            project, "feat.one", phase="report", status="report_ready",
            from_agent="claude-code",
            content="task: feat.one\nphase: report\nstatus: report_ready\n"
                    "from: claude-code\nto: owner\ndate: 2026-04-10T10:00:00Z\n"
                    "outcome: Done.\nverified: false\n",
            now="2026-04-10T10:00:00Z",
        )
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert len(task["handoffs"]) == 1
        h = task["handoffs"][0]
        assert h["phase"] == "report"
        assert h["from"] == "claude-code"
        assert h["status"] == "report_ready"

    def test_handoff_files_touched_alias(self, tmp_path):
        """`files_touched` in YAML must appear as `files_changed` in payload."""
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_handoff
        seed_sqlite_handoff(
            project, "feat.one", phase="report", status="report_ready",
            from_agent="claude-code",
            content="task: feat.one\nphase: report\nstatus: report_ready\n"
                    "from: claude-code\nto: owner\ndate: 2026-04-10T10:00:00Z\n"
                    "files_touched:\n  - src/foo.py\n",
            now="2026-04-10T10:00:00Z",
        )
        d = json.loads(_run(["--project", str(project)]).stdout)
        h = d["tasks"][0]["handoffs"][0]
        assert "files_changed" in h
        assert h["files_changed"] == ["src/foo.py"]

    def test_handoff_without_task_field_ignored(self, tmp_path):
        """YAML file with no `task:` key must not appear in any task's handoffs."""
        project = _setup(tmp_path)
        # No SQLite handoff seeded — should produce zero handoffs
        d = json.loads(_run(["--project", str(project)]).stdout)
        total = sum(len(t["handoffs"]) for t in d["tasks"])
        assert total == 0

    def test_handoffs_sorted_oldest_first(self, tmp_path):
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_handoff
        # Seed plan first (older), then report (newer) — adapter must sort oldest first
        seed_sqlite_handoff(
            project, "feat.one", phase="plan", status="plan_approved",
            from_agent="owner",
            content="task: feat.one\nphase: plan\nstatus: plan_approved\n"
                    "from: owner\nto: claude-code\ndate: 2026-04-11T08:00:00Z\n",
            now="2026-04-11T08:00:00Z",
        )
        seed_sqlite_handoff(
            project, "feat.one", phase="report", status="report_ready",
            from_agent="claude-code",
            content="task: feat.one\nphase: report\nstatus: report_ready\n"
                    "from: claude-code\nto: owner\ndate: 2026-04-12T10:00:00Z\n",
            now="2026-04-12T10:00:00Z",
        )
        d = json.loads(_run(["--project", str(project)]).stdout)
        hs = d["tasks"][0]["handoffs"]
        assert len(hs) == 2
        assert hs[0]["phase"] == "plan"   # older comes first
        assert hs[1]["phase"] == "report"


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class TestLedger:
    def test_ledger_entries_parsed(self, tmp_path):
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_ledger
        seed_sqlite_ledger(project, action="modified: foo.py", agent="claude-code",
                           now="2026-04-10T08:00:00Z")
        seed_sqlite_ledger(project, action="session-stop: snapshot written", agent="claude-code",
                           now="2026-04-11T09:00:00Z")
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert len(d["ledger"]) == 2

    def test_ledger_newest_first(self, tmp_path):
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_ledger
        seed_sqlite_ledger(project, action="modified: foo.py", agent="claude-code",
                           now="2026-04-10T08:00:00Z")
        seed_sqlite_ledger(project, action="modified: bar.py", agent="claude-code",
                           now="2026-04-11T09:00:00Z")
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["ledger"][0]["timestamp"] > d["ledger"][1]["timestamp"]

    def test_ledger_entry_fields(self, tmp_path):
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_ledger
        seed_sqlite_ledger(project, action="modified: foo.py", agent="claude-code",
                           now="2026-04-10T08:00:00Z")
        d = json.loads(_run(["--project", str(project)]).stdout)
        e = d["ledger"][0]
        assert "timestamp" in e
        assert "type" in e
        assert "description" in e

    def test_ledger_session_type(self, tmp_path):
        project = _setup(tmp_path)
        from tests.helpers import seed_sqlite_ledger
        seed_sqlite_ledger(project, action="session-stop: branch main", agent="claude-code",
                           now="2026-04-10T08:00:00Z")
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["ledger"][0]["type"] == "session"

    def test_empty_ledger_returns_empty_list(self, tmp_path):
        project = _setup(tmp_path)
        (project / ".superharness" / "ledger.md").write_text("# Ledger\n\n")
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["ledger"] == []


# ---------------------------------------------------------------------------
# Failures / Decisions / Inbox
# ---------------------------------------------------------------------------

class TestFailures:
    def test_failures_loaded(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import failures_dao
        project = _setup(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        failures_dao.record(conn, task_id="feat.one", agent="claude-code",
                            error_snippet="AssertionError", pattern="unknown",
                            now="2026-04-09T00:00:00Z")
        conn.commit()
        conn.close()
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert len(d["failures"]) == 1
        f = d["failures"][0]
        assert f["task"] == "feat.one"

    def test_empty_failures_returns_list(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert isinstance(d["failures"], list)


class TestDecisions:
    def test_decisions_loaded(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import decisions_dao
        project = _setup(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        decisions_dao.record(conn, agent="owner", task_id="feat.one",
                             decision="Use JWT", reason="Simple",
                             alternatives=["sessions"], now="2026-04-10T00:00:00Z")
        conn.commit()
        conn.close()
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert len(d["decisions"]) == 1
        assert d["decisions"][0]["what"] == "Use JWT"

    def test_empty_decisions_returns_list(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert isinstance(d["decisions"], list)


class TestInbox:
    def test_active_inbox_items_included(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao
        project = _setup(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        inbox_dao.enqueue(conn, id="inbox-001", task_id="feat.one",
                          target_agent="claude-code", priority=2,
                          now="2026-04-10T10:00:00Z")
        conn.commit()
        conn.close()
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert len(d["inbox"]) == 1
        assert d["inbox"][0]["id"] == "inbox-001"

    def test_done_inbox_items_excluded(self, tmp_path):
        """Completed inbox items must not appear in the payload."""
        project = _setup(tmp_path)
        (project / ".superharness" / "inbox.yaml").write_text(
            "- id: done-001\n  task: feat.one\n  status: done\n"
            "  to: claude-code\n  priority: 2\n  retry_count: 0\n"
            "  max_retries: 3\n  created_at: '2026-04-10T10:00:00Z'\n"
        )
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["inbox"] == []

    def test_all_active_statuses_included(self, tmp_path):
        from superharness.engine.db import get_connection, init_db
        from superharness.engine import inbox_dao, tasks_dao
        from superharness.engine.tasks_dao import TaskRow
        project = _setup(tmp_path)
        conn = get_connection(str(project))
        init_db(conn)
        # Seed a second unique task so we can enqueue 3 separate items
        tasks_dao.upsert(conn, TaskRow(
            id="feat.two", title="Feature two", owner="claude-code", status="in_progress",
            effort=None, project_path=str(project), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[],
            context=None, tdd=None, version=1, created_at="2026-04-10T00:00:00Z",
        ))
        tasks_dao.upsert(conn, TaskRow(
            id="feat.three", title="Feature three", owner="claude-code", status="in_progress",
            effort=None, project_path=str(project), development_method="tdd",
            acceptance_criteria=[], test_types=[], out_of_scope=[], definition_of_done=[],
            context=None, tdd=None, version=1, created_at="2026-04-10T00:00:00Z",
        ))
        now = "2026-04-10T10:00:00Z"
        inbox_dao.enqueue(conn, id="i1", task_id="feat.one", target_agent="claude-code", now=now)
        inbox_dao.enqueue(conn, id="i2", task_id="feat.two", target_agent="claude-code", now=now)
        inbox_dao.enqueue(conn, id="i3", task_id="feat.three", target_agent="claude-code", now=now)
        inbox_dao.update_status(conn, "i2", from_status="pending", to_status="launched", now=now)
        inbox_dao.update_status(conn, "i3", from_status="pending", to_status="running", now=now)
        conn.commit()
        conn.close()
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert len(d["inbox"]) == 3


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_missing_project_exits_nonzero(self, tmp_path):
        r = _run(["--project", str(tmp_path / "nonexistent")])
        assert r.returncode != 0

    def test_missing_project_error_on_stderr(self, tmp_path):
        r = _run(["--project", str(tmp_path / "nonexistent")])
        assert "error" in r.stderr.lower()

    def test_missing_project_nothing_on_stdout(self, tmp_path):
        r = _run(["--project", str(tmp_path / "nonexistent")])
        assert r.stdout.strip() == ""

    def test_project_flag_overrides_cwd(self, tmp_path):
        """--project PATH works even when cwd has no .superharness/."""
        project = _setup(tmp_path)
        r = _run(["--project", str(project)], cwd=str(tmp_path))
        assert r.returncode == 0
        d = json.loads(r.stdout)
        assert d["schema_version"] == "1.4"


# ---------------------------------------------------------------------------
# Agent pulse
# ---------------------------------------------------------------------------

import yaml as _yaml


class TestAgentPulsePayload:
    def test_agent_pulse_null_when_absent(self, tmp_path):
        """agent_pulse is null when no agent-pulse.yaml exists."""
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["agent_pulse"] is None

    def test_agent_pulse_present_when_file_exists(self, tmp_path):
        """agent_pulse is populated when agent-pulse.yaml is present."""
        project = _setup(tmp_path)
        sh = project / ".superharness"
        (sh / "agent-pulse.yaml").write_text(
            _yaml.dump({
                "task_id": "feat.one",
                "agent": "claude-code",
                "status": "running",
                "last_seen": "2026-04-12T10:00:00Z",
                "message": "compiling",
                "pid": 42,
            })
        )
        d = json.loads(_run(["--project", str(project)]).stdout)
        pulse = d["agent_pulse"]
        assert pulse is not None
        assert pulse["task_id"] == "feat.one"
        assert pulse["agent"] == "claude-code"
        assert pulse["status"] == "running"
        assert pulse["pid"] == 42

    def test_agent_pulse_null_on_corrupt_file(self, tmp_path):
        """agent_pulse is null when agent-pulse.yaml is corrupt YAML."""
        project = _setup(tmp_path)
        sh = project / ".superharness"
        (sh / "agent-pulse.yaml").write_text(":\t:\tinvalid{{{\n")
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["agent_pulse"] is None


# ---------------------------------------------------------------------------
# New status mapping (waiting_input / paused)
# ---------------------------------------------------------------------------


class TestNewStatusMapping:
    def test_waiting_input_maps_to_paused(self, tmp_path):
        """waiting_input status → display_status=paused, color=#f59e0b."""
        project = _setup(tmp_path, tasks=[{
            "id": "feat.wip", "title": "WIP", "owner": "claude-code",
            "status": "waiting_input",
        }])
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = next(t for t in d["tasks"] if t["id"] == "feat.wip")
        assert task["display_status"] == "paused"
        assert task["color"] == "#f59e0b"

    def test_paused_maps_to_paused(self, tmp_path):
        """paused status → display_status=paused, color=#f59e0b."""
        project = _setup(tmp_path, tasks=[{
            "id": "feat.paused", "title": "Paused", "owner": "claude-code",
            "status": "paused",
        }])
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = next(t for t in d["tasks"] if t["id"] == "feat.paused")
        assert task["display_status"] == "paused"
        assert task["color"] == "#f59e0b"


# ---------------------------------------------------------------------------
# Subtask decomposition
# ---------------------------------------------------------------------------

class TestSubtasks:
    def _setup_with_subtasks(self, tmp_path: "Path") -> "Path":
        project = tmp_path / "proj"
        sh = project / ".superharness"
        (sh / "handoffs").mkdir(parents=True)
        (sh / "failures.yaml").write_text("failures: []\n")
        (sh / "decisions.yaml").write_text("decisions: []\n")
        (sh / "inbox.yaml").write_text("# inbox\n")
        (sh / "ledger.md").write_text("# Ledger\n\n")
        (sh / "contract.yaml").write_text(
            "id: test-contract\ngoal: Test goal\ncreated: 2026-01-01\n"
            "created_by: owner\nstatus: active\ntasks:\n"
            "  - id: feat.parent\n    title: \"Parent task\"\n"
            "    owner: claude-code\n    status: in_progress\n"
            "    subtasks:\n"
            "      - id: feat.parent.st1\n        title: \"Subtask one\"\n"
            "        model_tier: mini\n        owner: claude-code\n"
            "        estimated_tokens: 8000\n        estimated_cost_usd: 0.005\n"
            "        rationale: \"Simple step\"\n"
            "      - id: feat.parent.st2\n        title: \"Subtask two\"\n"
            "        model_tier: standard\n        owner: claude-code\n"
            "        estimated_tokens: 25000\n        estimated_cost_usd: 0.19\n"
        )
        return project

    def test_subtasks_field_is_list(self, tmp_path):
        project = self._setup_with_subtasks(tmp_path)
        d = __import__('json').loads(__import__('subprocess').run(
            [__import__('sys').executable, "-m", "superharness.commands.adapter_payload",
             "--project", str(project)],
            cwd=str(project), text=True, capture_output=True,
            env={**__import__('os').environ, "PYTHONPATH": str(
                __import__('pathlib').Path(__file__).parent.parent.parent / "src"
            )}, check=False,
        ).stdout)
        task = next(t for t in d["tasks"] if t["id"] == "feat.parent")
        assert isinstance(task["subtasks"], list)
        assert len(task["subtasks"]) == 2

    def test_subtask_fields_present(self, tmp_path):
        project = self._setup_with_subtasks(tmp_path)
        d = __import__('json').loads(__import__('subprocess').run(
            [__import__('sys').executable, "-m", "superharness.commands.adapter_payload",
             "--project", str(project)],
            cwd=str(project), text=True, capture_output=True,
            env={**__import__('os').environ, "PYTHONPATH": str(
                __import__('pathlib').Path(__file__).parent.parent.parent / "src"
            )}, check=False,
        ).stdout)
        task = next(t for t in d["tasks"] if t["id"] == "feat.parent")
        st = task["subtasks"][0]
        for f in ("id", "title", "model_tier", "owner", "estimated_tokens",
                  "estimated_cost_usd", "rationale"):
            assert f in st, f"subtask missing field: {f}"
        assert st["id"] == "feat.parent.st1"
        assert st["model_tier"] == "mini"

    def test_task_without_subtasks_has_empty_list(self, tmp_path):
        from tests.helpers import REPO_ROOT
        project = _setup(tmp_path)
        d = __import__('json').loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert "subtasks" in task
        assert task["subtasks"] == []


# ── feat.adapter-payload-resolved-model: per-task resolved_model ─────────────

class TestResolvedModelField:
    """Each task and subtask carries resolved_model: {id, label} alongside model_tier."""

    def _setup_with_owner_and_tier(self, tmp_path: Path, owner: str, tier: str) -> Path:
        project = tmp_path / "proj_resolved"
        sh = project / ".superharness"
        (sh / "handoffs").mkdir(parents=True)
        (sh / "failures.yaml").write_text("failures: []\n")
        (sh / "decisions.yaml").write_text("decisions: []\n")
        (sh / "inbox.yaml").write_text("# inbox\n")
        (sh / "ledger.md").write_text("# Ledger\n\n")
        (sh / "contract.yaml").write_text(
            "id: test-contract\ngoal: G\ncreated: 2026-01-01\n"
            "created_by: owner\nstatus: active\n"
            "tasks:\n"
            f"  - id: feat.with-tier\n"
            f"    title: T\n"
            f"    owner: {owner}\n"
            f"    status: in_progress\n"
            f"    model_tier: {tier}\n"
            "    subtasks:\n"
            f"      - id: feat.with-tier.sub\n"
            f"        title: sub\n"
            f"        owner: {owner}\n"
            f"        model_tier: {tier}\n"
        )
        return project

    def test_task_has_resolved_model_id_and_label(self, tmp_path):
        project = self._setup_with_owner_and_tier(tmp_path, "claude-code", "standard")
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert "resolved_model" in task
        assert isinstance(task["resolved_model"], dict)
        assert task["resolved_model"]["label"] == "Sonnet 4.6"
        assert task["resolved_model"]["id"].startswith("claude-sonnet")

    def test_task_keeps_model_tier_for_backwards_compat(self, tmp_path):
        """model_tier string MUST stay in the payload (Morpheme fallback)."""
        project = self._setup_with_owner_and_tier(tmp_path, "claude-code", "standard")
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert task.get("model_tier") == "standard"

    def test_subtask_has_resolved_model(self, tmp_path):
        project = self._setup_with_owner_and_tier(tmp_path, "claude-code", "max")
        d = json.loads(_run(["--project", str(project)]).stdout)
        sub = d["tasks"][0]["subtasks"][0]
        assert sub["resolved_model"]["label"].startswith("Opus")
        assert sub["model_tier"] == "max"

    def test_codex_cli_owner_resolves_to_codex_model(self, tmp_path):
        project = self._setup_with_owner_and_tier(tmp_path, "codex-cli", "standard")
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert task["resolved_model"]["id"]
        assert task["resolved_model"]["label"]
        # codex tiers use gpt-* ids in the canonical mapping.
        assert task["resolved_model"]["id"].startswith("gpt")

    def test_unknown_owner_falls_back_to_tier_string(self, tmp_path):
        project = self._setup_with_owner_and_tier(tmp_path, "weird-agent", "standard")
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert task["resolved_model"] == {"id": "standard", "label": "standard"}

    def test_task_without_model_tier_omits_resolved_model_or_returns_empty(self, tmp_path):
        """A task with no model_tier set must not crash — resolved_model may be omitted."""
        project = tmp_path / "proj_no_tier"
        sh = project / ".superharness"
        (sh / "handoffs").mkdir(parents=True)
        (sh / "failures.yaml").write_text("failures: []\n")
        (sh / "decisions.yaml").write_text("decisions: []\n")
        (sh / "inbox.yaml").write_text("# inbox\n")
        (sh / "ledger.md").write_text("# Ledger\n\n")
        (sh / "contract.yaml").write_text(
            "id: c\ngoal: G\ncreated: 2026-01-01\ncreated_by: owner\nstatus: active\n"
            "tasks:\n"
            "  - id: feat.notier\n    title: T\n    owner: claude-code\n    status: todo\n"
        )
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        d = json.loads(r.stdout)
        task = d["tasks"][0]
        # resolved_model either absent or null/empty — no crash either way.
        rm = task.get("resolved_model")
        assert rm is None or rm == {} or (isinstance(rm, dict) and not rm.get("label"))


class TestSchemaVersionBump:
    def test_schema_version_bumped_to_1_2(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["schema_version"] == "1.4"


# ---------------------------------------------------------------------------
# Schema v1.2 — classifier / decomposer / retry blocks
# ---------------------------------------------------------------------------

def _setup_v12(tmp_path: Path, *, classifier: dict | None = None,
               decomposer: dict | None = None, retry: dict | None = None) -> Path:
    """Create a project whose single task carries v1.2 pipeline fields."""
    project = tmp_path / "proj_v12"
    sh = project / ".superharness"
    (sh / "handoffs").mkdir(parents=True)
    for f in ("failures.yaml", "decisions.yaml"):
        (sh / f).write_text(f"{f.split('.')[0]}: []\n")
    (sh / "inbox.yaml").write_text("# inbox\n")
    (sh / "ledger.md").write_text("# Ledger\n\n")

    import yaml as _yaml
    task = {
        "id": "feat.v12-task",
        "title": "V1.2 test task",
        "owner": "claude-code",
        "status": "in_progress",
    }
    if classifier is not None:
        task["classifier"] = classifier
    if decomposer is not None:
        task["decomposer"] = decomposer
    if retry is not None:
        task["retry"] = retry

    (sh / "contract.yaml").write_text(
        _yaml.dump({
            "id": "c", "goal": "G", "created": "2026-01-01",
            "created_by": "owner", "status": "active",
            "tasks": [task],
        })
    )
    return project


class TestSchemaV12:
    """adapter-payload v1.2: classifier, decomposer, retry blocks on each task."""

    def test_schema_version_is_1_3(self, tmp_path):
        """Schema version string must be '1.3'."""
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["schema_version"] == "1.4"

    def test_task_has_classifier_block(self, tmp_path):
        """Every task carries a classifier block (defaults when not set in YAML)."""
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert "classifier" in task
        assert isinstance(task["classifier"], dict)
        assert task["classifier"]["invoked"] is False

    def test_task_has_decomposer_block(self, tmp_path):
        """Every task carries a decomposer block (defaults when not set in YAML)."""
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert "decomposer" in task
        assert isinstance(task["decomposer"], dict)
        assert task["decomposer"]["invoked"] is False

    def test_task_has_retry_block(self, tmp_path):
        """Every task carries a retry block with count=0 and empty history by default."""
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        task = d["tasks"][0]
        assert "retry" in task
        assert task["retry"]["count"] == 0
        assert task["retry"]["escalation_history"] == []

    def test_classifier_block_invoked_when_set(self, tmp_path):
        """When task.classifier is set in YAML, it is surfaced in the payload."""
        project = _setup_v12(tmp_path, classifier={
            "invoked": True,
            "decided_by": "heuristic",
            "heuristic_reason": "title matches OPUS_KEYWORDS",
            "cost_usd": None,
            "duration_ms": None,
        })
        d = json.loads(_run(["--project", str(project)]).stdout)
        clf = d["tasks"][0]["classifier"]
        assert clf["invoked"] is True
        assert clf["decided_by"] == "heuristic"
        assert clf["heuristic_reason"] == "title matches OPUS_KEYWORDS"

    def test_decomposer_block_with_data(self, tmp_path):
        """When task.decomposer is set in YAML, all fields are surfaced."""
        project = _setup_v12(tmp_path, decomposer={
            "invoked": True,
            "model": "claude-opus-4-6",
            "rationale": "AC=6, complex task",
            "cost_usd": 0.08,
            "duration_ms": 4200,
            "subtask_count": 3,
        })
        d = json.loads(_run(["--project", str(project)]).stdout)
        dec = d["tasks"][0]["decomposer"]
        assert dec["invoked"] is True
        assert dec["model"] == "claude-opus-4-6"
        assert dec["subtask_count"] == 3
        assert dec["cost_usd"] == pytest.approx(0.08)

    def test_retry_block_with_count(self, tmp_path):
        """retry.count is surfaced when set; escalation_history preserved."""
        project = _setup_v12(tmp_path, retry={
            "count": 2,
            "escalation_history": ["sonnet-4-6", "opus-4-6"],
        })
        d = json.loads(_run(["--project", str(project)]).stdout)
        retry = d["tasks"][0]["retry"]
        assert retry["count"] == 2
        assert retry["escalation_history"] == ["sonnet-4-6", "opus-4-6"]


# ---------------------------------------------------------------------------
# Schema v1.3 — next_action field
# ---------------------------------------------------------------------------

class TestNextActionInPayload:
    """Every task in the adapter-payload must carry a next_action dict (schema v1.3)."""

    def _task_with_status(self, tmp_path: Path, status: str) -> dict:
        project = tmp_path / f"proj_{status}"
        sh = project / ".superharness"
        (sh / "handoffs").mkdir(parents=True)
        for f, content in [
            ("failures.yaml", "failures: []\n"),
            ("decisions.yaml", "decisions: []\n"),
            ("inbox.yaml", "# inbox\n"),
            ("ledger.md", "# Ledger\n\n"),
        ]:
            (sh / f).write_text(content)
        (sh / "contract.yaml").write_text(
            "id: test-contract\ngoal: G\ncreated: 2026-01-01\n"
            "created_by: owner\nstatus: active\n"
            f"tasks:\n  - id: t1\n    title: T\n    owner: claude-code\n    status: {status}\n"
        )
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)["tasks"][0]

    def test_schema_version_is_1_3(self, tmp_path):
        project = _setup(tmp_path)
        d = json.loads(_run(["--project", str(project)]).stdout)
        assert d["schema_version"] == "1.4"

    def test_next_action_present_on_every_task(self, tmp_path):
        project = _setup(tmp_path, tasks=[
            {"id": "feat.one", "title": "F", "owner": "claude-code", "status": "todo"},
            {"id": "feat.two", "title": "G", "owner": "claude-code", "status": "in_progress"},
        ])
        d = json.loads(_run(["--project", str(project)]).stdout)
        for task in d["tasks"]:
            assert "next_action" in task, f"task {task['id']} missing next_action"

    def test_next_action_shape(self, tmp_path):
        task = self._task_with_status(tmp_path, "todo")
        na = task["next_action"]
        assert set(na.keys()) == {"recommended", "legal", "reason"}
        assert isinstance(na["legal"], list)
        assert isinstance(na["reason"], str)

    def test_todo_recommends_plan_proposed(self, tmp_path):
        na = self._task_with_status(tmp_path, "todo")["next_action"]
        assert na["recommended"] == "plan_proposed"
        assert "plan_proposed" in na["legal"]

    def test_in_progress_recommended_is_null(self, tmp_path):
        na = self._task_with_status(tmp_path, "in_progress")["next_action"]
        assert na["recommended"] is None
        assert len(na["legal"]) > 0

    def test_done_is_terminal(self, tmp_path):
        na = self._task_with_status(tmp_path, "done")["next_action"]
        assert na["recommended"] is None
        assert na["legal"] == []

    def test_recommended_is_member_of_legal_or_null(self, tmp_path):
        for status in ("todo", "plan_proposed", "plan_approved", "report_ready",
                       "review_passed", "review_failed", "failed", "stopped"):
            na = self._task_with_status(tmp_path, status)["next_action"]
            if na["recommended"] is not None:
                assert na["recommended"] in na["legal"], (
                    f"status={status}: recommended not in legal"
                )


# ---------------------------------------------------------------------------
# Schema v1.4 — project_settings + per-task autonomy/require_tdd (Iteration 5)
# ---------------------------------------------------------------------------

class TestSchemaV14:
    """Adapter-payload schema v1.4 tests."""

    @staticmethod
    def _make_project(tmp_path, profile=None, tasks=None):
        project = tmp_path / "proj"
        sh = project / ".superharness"
        sh.mkdir(parents=True)
        for f, content in [
            ("failures.yaml", "failures: []\n"),
            ("decisions.yaml", "decisions: []\n"),
            ("inbox.yaml", "# inbox\n"),
            ("ledger.md", "# Ledger\n\n"),
        ]:
            (sh / f).write_text(content)
        import yaml as _yaml
        if profile is not None:
            (sh / "profile.yaml").write_text(_yaml.dump(profile))
        task_list = tasks or [
            {"id": "t1", "title": "T", "owner": "claude-code", "status": "todo"}
        ]
        contract = {
            "id": "test",
            "goal": "G",
            "tasks": task_list,
        }
        (sh / "contract.yaml").write_text(_yaml.dump(contract))
        return project

    @staticmethod
    def _payload(project):
        r = _run(["--project", str(project)])
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    def test_schema_version_is_1_4(self, tmp_path):
        """Schema version must be 1.4 after this bump."""
        project = self._make_project(tmp_path)
        d = self._payload(project)
        assert d["schema_version"] == "1.4"

    def test_project_settings_block_present(self, tmp_path):
        """Top-level project_settings key must exist."""
        project = self._make_project(tmp_path)
        d = self._payload(project)
        assert "project_settings" in d

    def test_project_settings_defaults_when_profile_absent(self, tmp_path):
        """No profile.yaml → project_settings has safe defaults."""
        project = self._make_project(tmp_path, profile=None)
        ps = self._payload(project)["project_settings"]
        assert ps["autonomy"] == "ai_driven"
        assert ps["workflow"]["default_preset"] == "implementation"
        assert ps["workflow"]["require_tdd"] is True

    def test_project_settings_reflects_profile(self, tmp_path):
        """profile.yaml values appear in project_settings."""
        project = self._make_project(tmp_path, profile={
            "autonomy": "oversight",
            "workflow": {"default_preset": "quick", "require_tdd": False},
        })
        ps = self._payload(project)["project_settings"]
        assert ps["autonomy"] == "oversight"
        assert ps["workflow"]["default_preset"] == "quick"
        assert ps["workflow"]["require_tdd"] is False

    def test_task_emits_workflow_and_development_method(self, tmp_path):
        """Task with workflow + development_method → both appear in payload."""
        project = self._make_project(tmp_path, tasks=[{
            "id": "t1", "title": "T", "owner": "claude-code", "status": "todo",
            "workflow": "implementation",
            "development_method": "tdd",
        }])
        task = self._payload(project)["tasks"][0]
        assert task["workflow"] == "implementation"
        assert task["development_method"] == "tdd"

    def test_task_emits_autonomy_and_require_tdd(self, tmp_path):
        """Task with stamped autonomy + require_tdd → both appear in payload."""
        project = self._make_project(tmp_path, tasks=[{
            "id": "t1", "title": "T", "owner": "claude-code", "status": "todo",
            "autonomy": "oversight",
            "require_tdd": False,
        }])
        task = self._payload(project)["tasks"][0]
        assert task["autonomy"] == "oversight"
        assert task["require_tdd"] is False

    def test_pre_existing_task_defaults_when_unstamped(self, tmp_path):
        """Task without autonomy/require_tdd → payload shows safe defaults."""
        project = self._make_project(tmp_path, tasks=[{
            "id": "t1", "title": "T", "owner": "claude-code", "status": "todo",
            # no autonomy, no require_tdd, no workflow
        }])
        task = self._payload(project)["tasks"][0]
        assert task["autonomy"] == "ai_driven"
        assert task["require_tdd"] is True
        assert task["workflow"] is None
        assert task["development_method"] is None
