"""Tests for the /api/observation/<id> route helper.

The route is implemented as a pure function (path, conn) -> (payload, status)
so it can be unit-tested without spinning up the dashboard HTTP server.
The dashboard handler just delegates to this function.
"""
from __future__ import annotations

import pytest

from superharness.engine.db import get_connection, init_db
from superharness.engine import observations_dao
from superharness.commands.observation import (
    parse_observation_id,
    fetch_observation,
    route_observation,
)


@pytest.fixture
def conn(tmp_path):
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    c = get_connection(str(project_dir))
    init_db(c, str(project_dir))
    yield c
    c.close()


def test_parse_id_accepts_positive_integer():
    assert parse_observation_id("42") == 42


def test_parse_id_rejects_zero():
    with pytest.raises(ValueError):
        parse_observation_id("0")


def test_parse_id_rejects_negative():
    with pytest.raises(ValueError):
        parse_observation_id("-1")


def test_parse_id_rejects_non_numeric():
    with pytest.raises(ValueError):
        parse_observation_id("abc")


def test_parse_id_rejects_empty():
    with pytest.raises(ValueError):
        parse_observation_id("")


def test_fetch_observation_found(conn):
    new_id = observations_dao.insert(conn, "t-1", "report_ready", "did things")
    row = fetch_observation(conn, new_id)
    assert row["id"] == new_id
    assert row["task_id"] == "t-1"


def test_fetch_observation_missing_returns_none(conn):
    assert fetch_observation(conn, 9999) is None


def test_route_observation_200_when_found(conn):
    new_id = observations_dao.insert(conn, "t-1", "report_ready", "did things")
    payload, status = route_observation(conn, str(new_id))
    assert status == 200
    assert payload["task_id"] == "t-1"
    assert payload["summary"] == "did things"
    assert payload["id"] == new_id


def test_route_observation_404_when_missing(conn):
    payload, status = route_observation(conn, "9999")
    assert status == 404
    assert "error" in payload
    assert payload["error"] == "not found"


def test_route_observation_400_when_invalid_id(conn):
    payload, status = route_observation(conn, "abc")
    assert status == 400
    assert payload["error"] == "invalid id"


def test_route_observation_400_when_zero(conn):
    payload, status = route_observation(conn, "0")
    assert status == 400


def test_route_observation_400_when_negative(conn):
    payload, status = route_observation(conn, "-3")
    assert status == 400
