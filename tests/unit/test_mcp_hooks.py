"""Tests for MCP HookRegistry — Iteration 2."""
from __future__ import annotations

import pytest
from pathlib import Path

from superharness.mcp.hooks import HookRegistry


def test_register_and_fire_hook(tmp_path):
    reg = HookRegistry()
    received = []
    reg.register("task:delegated", lambda p: received.append(p), project_path=str(tmp_path))
    reg.fire("task:delegated", {"task_id": "t1"}, project_path=str(tmp_path))
    assert received == [{"task_id": "t1"}]


def test_hook_fires_project_scoped(tmp_path):
    proj_a = str(tmp_path / "a")
    proj_b = str(tmp_path / "b")
    reg = HookRegistry()
    received = []
    reg.register("task:delegated", lambda p: received.append(p), project_path=proj_a)
    reg.fire("task:delegated", {"task_id": "t1"}, project_path=proj_b)
    assert received == []


def test_fire_unknown_event_is_noop(tmp_path):
    reg = HookRegistry()
    reg.fire("unknown:event", {}, project_path=str(tmp_path))  # must not raise


def test_hook_exception_does_not_crash_server(tmp_path):
    reg = HookRegistry()
    def bad_handler(p):
        raise RuntimeError("boom")
    reg.register("task:completed", bad_handler, project_path=str(tmp_path))
    reg.fire("task:completed", {}, project_path=str(tmp_path))  # must not raise


def test_multiple_handlers_all_called(tmp_path):
    reg = HookRegistry()
    calls = []
    reg.register("task:failed", lambda p: calls.append("h1"), project_path=str(tmp_path))
    reg.register("task:failed", lambda p: calls.append("h2"), project_path=str(tmp_path))
    reg.fire("task:failed", {}, project_path=str(tmp_path))
    assert calls == ["h1", "h2"]


def test_unregister_removes_handler(tmp_path):
    reg = HookRegistry()
    calls = []
    handler = lambda p: calls.append("x")
    reg.register("task:closed", handler, project_path=str(tmp_path))
    reg.unregister("task:closed", handler, project_path=str(tmp_path))
    reg.fire("task:closed", {}, project_path=str(tmp_path))
    assert calls == []
