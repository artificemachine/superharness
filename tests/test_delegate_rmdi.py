"""routing_strategy: rmdi — delegate resolves models through the RMDI router.

Unit tests over the graft points (no live router): seat mapping, adapter
selection from the binding endpoint, edge-denial permanent block, fail-loud
router-down, and (seat, bindingVersion, modelRef) provenance in
tasks.extras_json + the ledger.
"""

from __future__ import annotations

import json

import pytest

from superharness.commands import delegate as delegate_mod
from superharness.commands.delegate import (
    EXIT_PERMANENT_BLOCK,
    _record_rmdi_provenance,
    _resolve_via_rmdi,
)
from superharness.engine.rmdi_client import RmdiError, RmdiRouterDown


def _dispatch_response(model_ref: str, version: int = 3, recipe: str = "shux-orchestrator") -> dict:
    provider = model_ref.split("/", 1)[0]
    return {
        "binding": {
            "seatID": "worker@shux",
            "modelSpec": {"providerID": provider, "modelID": model_ref.split("/", 1)[1]},
            "version": version,
            "by": "recipe",
            "regime": "ddap",
        },
        "modelRef": model_ref,
        "activeRecipe": recipe,
        "baseUrl": "http://10.255.150.36:8000/v1",
        "roleClass": {"name": "worker", "prompt": None, "permission": {"*": "allow"}},
        "seatConfig": None,
    }


@pytest.fixture
def project(tmp_path):
    return str(tmp_path)


def test_resolve_maps_role_to_seat_and_endpoint_to_adapter(project, monkeypatch):
    calls = {}

    def fake_dispatch(seat, from_seat=None, consent=False):
        calls["seat"] = seat
        calls["from_seat"] = from_seat
        return _dispatch_response("vm913-direct/qwen3.6-27b")

    monkeypatch.setattr("superharness.engine.rmdi_client.dispatch", fake_dispatch)
    res = _resolve_via_rmdi(project, "worker", "T-1")
    assert calls["seat"] == "worker@shux"
    assert res["adapter"] == "opencode"  # vm913-direct matches the "*" adapter
    assert res["model"] == "vm913-direct/qwen3.6-27b"  # full ref for non-claude adapters
    assert res["bindingVersion"] == 3
    assert res["recipe"] == "shux-orchestrator"


def test_claude_endpoint_gets_bare_model_id_and_claude_adapter(project, monkeypatch):
    monkeypatch.setattr(
        "superharness.engine.rmdi_client.dispatch",
        lambda seat, from_seat=None, consent=False: _dispatch_response("claude/claude-sonnet-5"),
    )
    res = _resolve_via_rmdi(project, "reviewer", "T-1")
    assert res["adapter"] == "claude-code"
    assert res["model"] == "claude-sonnet-5"  # bare id — the claude CLI takes no provider prefix
    assert res["modelRef"] == "claude/claude-sonnet-5"


def test_edge_denied_is_a_permanent_block(project, monkeypatch):
    def deny(seat, from_seat=None, consent=False):
        raise RmdiError(409, "EDGE_DENIED", {"recipe": "shux-orchestrator", "to": seat})

    monkeypatch.setattr("superharness.engine.rmdi_client.dispatch", deny)
    with pytest.raises(SystemExit) as exc:
        _resolve_via_rmdi(project, "worker", "T-1", non_interactive=True)
    assert exc.value.code == EXIT_PERMANENT_BLOCK


def test_consent_required_blocks_without_tty(project, monkeypatch):
    def gated(seat, from_seat=None, consent=False):
        raise RmdiError(428, "EDGE_CONSENT_REQUIRED", {"to": seat})

    monkeypatch.setattr("superharness.engine.rmdi_client.dispatch", gated)
    with pytest.raises(SystemExit) as exc:
        _resolve_via_rmdi(project, "worker", "T-1", non_interactive=True)
    assert exc.value.code == EXIT_PERMANENT_BLOCK


def test_router_down_fails_loud(project, monkeypatch):
    def down(seat, from_seat=None, consent=False):
        raise RmdiRouterDown("connection refused")

    monkeypatch.setattr("superharness.engine.rmdi_client.dispatch", down)
    # RmdiRouterDown propagates — delegation halts, no silent native fallback.
    with pytest.raises(RmdiRouterDown):
        _resolve_via_rmdi(project, "worker", "T-1")


def test_profile_seat_and_adapter_maps_override_defaults(project, monkeypatch, tmp_path):
    sh = tmp_path / ".superharness"
    sh.mkdir()
    (sh / "profile.yaml").write_text(
        "routing_strategy: rmdi\n"
        "rmdi:\n"
        "  seat_map:\n"
        "    worker: executor@shux\n"
        "  adapter_map:\n"
        "    vm913-direct: claude-code\n"
    )
    seen = {}

    def fake_dispatch(seat, from_seat=None, consent=False):
        seen["seat"] = seat
        return _dispatch_response("vm913-direct/qwen3.6-27b")

    monkeypatch.setattr("superharness.engine.rmdi_client.dispatch", fake_dispatch)
    res = _resolve_via_rmdi(str(tmp_path), "worker", "T-1")
    assert seen["seat"] == "executor@shux"
    assert res["adapter"] == "claude-code"
    assert res["model"] == "qwen3.6-27b"


def test_provenance_lands_in_extras_json_and_ledger(project):
    from superharness.engine.db import get_connection, init_db

    conn = get_connection(project)
    init_db(conn)
    conn.execute(
        "INSERT INTO tasks (id, title, owner, status, created_at) VALUES ('T-9', 'rmdi provenance', 'opencode', 'todo', '2026-07-09T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    resolution = {
        "seat": "worker@shux",
        "bindingVersion": 7,
        "modelRef": "vm913-direct/qwen3.6-27b",
        "adapter": "opencode",
        "recipe": "shux-orchestrator",
        "regime": "ddap",
    }
    _record_rmdi_provenance(project, "T-9", resolution)

    conn = get_connection(project)
    row = conn.execute("SELECT extras_json FROM tasks WHERE id = 'T-9'").fetchone()
    extras = json.loads(row[0])
    assert extras["rmdi"]["seat"] == "worker@shux"
    assert extras["rmdi"]["bindingVersion"] == 7
    assert extras["rmdi"]["modelRef"] == "vm913-direct/qwen3.6-27b"
    assert extras["rmdi"]["recipe"] == "shux-orchestrator"

    ledger = conn.execute(
        "SELECT details FROM ledger WHERE action = 'rmdi_dispatch' AND task_id = 'T-9'"
    ).fetchall()
    conn.close()
    assert ledger, "no rmdi_dispatch ledger row"
    details = json.loads(ledger[0][0])
    assert "worker@shux v7" in details["reason"]
    assert details["bindingVersion"] == 7
    assert details["seat"] == "worker@shux"
