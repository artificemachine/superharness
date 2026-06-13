"""Tests for the on_delegate lifecycle hook firing.

Wires `run_hooks("on_delegate", ...)` into the delegate command via a small
helper so openclaw routing (conditional) and telegram notify actually fire on
dispatch. Previously on_delegate was a declared-but-never-fired event.
"""
from __future__ import annotations

from pathlib import Path

import superharness.modules.runner as runner_mod
from superharness.commands import delegate as delegate_mod


def test_fire_on_delegate_passes_target_and_event(monkeypatch):
    calls = []
    monkeypatch.setattr(
        runner_mod, "run_hooks",
        lambda event, ctx, pdir: calls.append((event, ctx, pdir)) or [],
    )
    # _get_task_title reads project state; stub it so the helper stays unit-scoped.
    monkeypatch.setattr(delegate_mod, "_get_task_title", lambda pd, tid: "Build it")

    delegate_mod._fire_on_delegate("/tmp/proj", "openclaw", "feat-001")

    on_delegate = [c for c in calls if c[0] == "on_delegate"]
    assert len(on_delegate) == 1
    _, ctx, pdir = on_delegate[0]
    assert ctx["target"] == "openclaw"
    assert ctx["task_id"] == "feat-001"
    assert ctx["event"] == "on_delegate"
    assert ctx["task_title"] == "Build it"
    # Compare as Path objects so the assertion is separator-agnostic (Windows
    # renders str(Path("/tmp/proj")) as "\\tmp\\proj").
    assert pdir == Path("/tmp/proj")


def test_fire_on_delegate_swallows_hook_errors(monkeypatch):
    """A failing on_delegate hook must never break dispatch."""
    def _boom(event, ctx, pdir):
        raise RuntimeError("hook exploded")

    monkeypatch.setattr(runner_mod, "run_hooks", _boom)
    monkeypatch.setattr(delegate_mod, "_get_task_title", lambda pd, tid: "x")

    # Must not raise.
    delegate_mod._fire_on_delegate("/tmp/proj", "claude-code", "feat-001")
