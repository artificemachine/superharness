"""Tests for the citation route helpers used by the dashboard.

Covers four record kinds (observation, handoff, decision, failure)
plus the per-task observations list. Each route is a pure
(conn, ...) -> (payload, status) helper, so we can unit-test without
spinning up the HTTP server.
"""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db, now_iso
from superharness.engine import handoffs_dao, decisions_dao, failures_dao, observations_dao
from superharness.commands.citation import (
    CITATION_KINDS,
    route_citation,
    route_task_observations,
)


@pytest.fixture
def conn(tmp_path):
    p = tmp_path / "proj"
    p.mkdir()
    c = get_connection(str(p))
    init_db(c, str(p))
    # Seed a task so foreign keys hold
    c.execute(
        "INSERT INTO tasks (id, title, status, version, created_at) VALUES (?, ?, ?, ?, ?)",
        ("t-1", "sample", "in_progress", 1, now_iso()),
    )
    c.commit()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Kinds and id-parsing
# ---------------------------------------------------------------------------

def test_all_expected_kinds():
    assert CITATION_KINDS == {"observation", "handoff", "decision", "failure"}


def test_invalid_kind_returns_400(conn):
    payload, status = route_citation(conn, "made-up", "1")
    assert status == 400
    assert payload["error"] == "invalid kind"


def test_invalid_id_returns_400(conn):
    payload, status = route_citation(conn, "handoff", "abc")
    assert status == 400
    assert payload["error"] == "invalid id"


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------

def test_handoff_route_200(conn):
    row = handoffs_dao.append(
        conn,
        task_id="t-1",
        phase="report",
        status="report_ready",
        from_agent="claude-code",
        to_agent="owner",
        content="ok",
        metadata={"k": "v"},
        now=now_iso(),
    )
    payload, status = route_citation(conn, "handoff", str(row.id))
    assert status == 200
    assert payload["id"] == row.id
    assert payload["task_id"] == "t-1"
    assert payload["metadata"] == {"k": "v"}


def test_handoff_route_404_when_missing(conn):
    payload, status = route_citation(conn, "handoff", "9999")
    assert status == 404
    assert payload["error"] == "not found"


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def test_decision_route_200(conn):
    row = decisions_dao.record(
        conn, task_id="t-1", decision="picked A", reason="best fit", now=now_iso()
    )
    payload, status = route_citation(conn, "decision", str(row.id))
    assert status == 200
    assert payload["id"] == row.id
    assert payload["decision"] == "picked A"


def test_decision_route_404(conn):
    payload, status = route_citation(conn, "decision", "9999")
    assert status == 404


# ---------------------------------------------------------------------------
# Failure
# ---------------------------------------------------------------------------

def test_failure_route_200(conn):
    row = failures_dao.record(
        conn, task_id="t-1", pattern="tests failed", error_snippet="flaky", now=now_iso()
    )
    payload, status = route_citation(conn, "failure", str(row.id))
    assert status == 200
    assert payload["id"] == row.id
    assert payload["pattern"] == "tests failed"


def test_failure_route_404(conn):
    payload, status = route_citation(conn, "failure", "9999")
    assert status == 404


# ---------------------------------------------------------------------------
# Observation (delegates to existing DAO)
# ---------------------------------------------------------------------------

def test_observation_route_200(conn):
    oid = observations_dao.insert(conn, "t-1", "report_ready", "did stuff")
    payload, status = route_citation(conn, "observation", str(oid))
    assert status == 200
    assert payload["id"] == oid


def test_observation_route_404(conn):
    payload, status = route_citation(conn, "observation", "9999")
    assert status == 404


# ---------------------------------------------------------------------------
# Task observations list
# ---------------------------------------------------------------------------

def test_task_observations_empty_is_200(conn):
    payload, status = route_task_observations(conn, "unknown-task")
    assert status == 200
    assert payload == {"task_id": "unknown-task", "observations": []}


def test_task_observations_returns_ordered_list(conn):
    observations_dao.insert(conn, "t-1", "report_ready", "first")
    observations_dao.insert(conn, "t-1", "report_ready", "second")
    payload, status = route_task_observations(conn, "t-1")
    assert status == 200
    summaries = [o["summary"] for o in payload["observations"]]
    assert summaries == ["first", "second"]


def test_task_observations_empty_task_id_400(conn):
    payload, status = route_task_observations(conn, "")
    assert status == 400
