"""Tests for the Harness protocol + registry + Claude adapter.

See docs/PLAN-steal-omnigent.md iteration 5.

Resolved ambiguity (see docs/PLAN-steal-omnigent.md executor report):
inbox_dispatch.py never builds per-agent CLI argv directly — it always
shells out generically to `python -m superharness.commands.delegate --to
<agent> ...`. The actual per-agent invocation assembly (agent binary via a
bash launcher script resolved from adapter_registry manifests) lives in
delegate.py's `_launch_agent()`. The registry is wired there instead, for
the claude-code target only (this iteration); other agents keep the legacy
path until iteration 6.

The golden parity value below was captured from the LIVE legacy code path
(delegate.py::_launch_agent with platform_runtime.launch_agent mocked to
record its argv/cwd instead of exec'ing) before the harness adapter existed,
per the plan's "capture first, hardcode, then extract" instruction.
"""
from __future__ import annotations

import pytest

from superharness.harnesses import KNOWN_HARNESSES, get_harness
from superharness.harnesses.base import Invocation


def test_registry_returns_claude_adapter():
    harness = get_harness("claude-code")
    assert harness.name == "claude-code"


def test_unknown_harness_raises_keyerror_with_known_list():
    with pytest.raises(KeyError) as excinfo:
        get_harness("not-a-real-harness")
    assert "claude-code" in str(excinfo.value)


def test_claude_invocation_parity():
    """Golden: argv must equal the value captured from the live legacy path
    (delegate.py::_launch_agent, target='claude-code', model set, prompt
    'do the thing', project_dir='/tmp/proj', non_interactive=True).
    """
    from superharness.engine.adapter_registry import resolve_launcher
    from pathlib import Path
    import superharness

    scripts_dir = str(Path(superharness.__file__).parent / "scripts")
    launcher = resolve_launcher("claude-code", scripts_dir)

    harness = get_harness("claude-code")
    invocation = harness.build_invocation(
        task={"prompt": "do the thing", "model": "claude-sonnet-4-6"},
        project_dir="/tmp/proj",
        non_interactive=True,
    )

    expected_argv = (
        "bash", launcher, "--project", "/tmp/proj", "--prompt", "do the thing",
        "--non-interactive", "--model", "claude-sonnet-4-6",
    )
    assert invocation.argv == expected_argv
    assert invocation.cwd == "/tmp/proj"
    assert invocation.env == {}


def test_invocation_is_frozen():
    inv = Invocation(argv=("claude",), env={}, cwd="/tmp")
    with pytest.raises(Exception):
        inv.argv = ("other",)
    with pytest.raises(Exception):
        inv.argv[0] = "other"  # tuple: item assignment must also fail


def test_prompt_passed_as_single_argv_element():
    dangerous = 'do the thing; rm -rf / && echo "pwned"'
    harness = get_harness("claude-code")
    invocation = harness.build_invocation(
        task={"prompt": dangerous},
        project_dir="/tmp/proj",
        non_interactive=True,
    )
    assert dangerous in invocation.argv
    assert invocation.argv.count(dangerous) == 1
