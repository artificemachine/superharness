"""Tests for the codex/gemini/opencode harness adapters + full dispatch
switchover through the registry.

See docs/PLAN-steal-omnigent.md iteration 6.

Golden values captured from the LIVE legacy code path (delegate.py::
_launch_agent with platform_runtime.launch_agent mocked to record argv/cwd
instead of exec'ing) before these adapters existed, per the plan's
"capture first, hardcode, then extract" instruction. See the iteration 5
test file (test_harness_registry.py) for the same pattern applied to
claude-code.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from superharness.harnesses import KNOWN_HARNESSES, get_harness
from superharness.engine.adapter_registry import resolve_launcher
import superharness


def _scripts_dir() -> str:
    return str(Path(superharness.__file__).parent / "scripts")


def test_codex_invocation_parity():
    launcher = resolve_launcher("codex-cli", _scripts_dir())
    invocation = get_harness("codex-cli").build_invocation(
        task={"prompt": "do the thing", "model": "gpt-5-codex", "effort": "high"},
        project_dir="/tmp/proj",
        non_interactive=True,
    )
    assert invocation.argv == (
        "bash", launcher, "--project", "/tmp/proj", "--prompt", "do the thing",
        "--non-interactive", "--model", "openai/gpt-5-codex", "--effort", "high",
    )
    assert invocation.cwd == "/tmp/proj"


def test_gemini_invocation_parity():
    launcher = resolve_launcher("gemini-cli", _scripts_dir())
    invocation = get_harness("gemini-cli").build_invocation(
        task={"prompt": "do the thing", "model": "gemini-3-pro"},
        project_dir="/tmp/proj",
        non_interactive=True,
    )
    assert invocation.argv == (
        "bash", launcher, "--project", "/tmp/proj", "--prompt", "do the thing",
        "--non-interactive", "--model", "google/gemini-3-pro",
    )
    assert invocation.cwd == "/tmp/proj"


def test_opencode_invocation_parity():
    launcher = resolve_launcher("opencode", _scripts_dir())
    invocation = get_harness("opencode").build_invocation(
        task={"prompt": "do the thing", "model": "claude-sonnet-4-6"},
        project_dir="/tmp/proj",
        non_interactive=True,
    )
    assert invocation.argv == (
        "bash", launcher, "--project", "/tmp/proj", "--prompt", "do the thing",
        "--non-interactive", "--model", "anthropic/claude-sonnet-4-6",
    )
    assert invocation.cwd == "/tmp/proj"


def test_all_known_harnesses_resolve():
    assert set(KNOWN_HARNESSES) == {"claude-code", "codex-cli", "gemini-cli", "opencode"}
    for name in KNOWN_HARNESSES:
        invocation = get_harness(name).build_invocation(
            task={"prompt": "do the thing"},
            project_dir="/tmp/proj",
            non_interactive=True,
        )
        assert len(invocation.argv) > 0


def test_prompt_injection_safety_all_adapters():
    dangerous = 'do the thing; rm -rf / && echo "pwned"'
    for name in KNOWN_HARNESSES:
        invocation = get_harness(name).build_invocation(
            task={"prompt": dangerous},
            project_dir="/tmp/proj",
            non_interactive=True,
        )
        assert dangerous in invocation.argv
        assert invocation.argv.count(dangerous) == 1


def test_unknown_owner_fails_dispatch_cleanly(monkeypatch):
    """Chaos: an unknown owner string fails cleanly via the registry's
    KeyError-with-known-list, not a stuck/hung dispatch."""
    from superharness.commands import delegate

    with pytest.raises(SystemExit):
        delegate._launch_agent(
            target="not-a-real-agent",
            prompt="do the thing",
            project_dir="/tmp/proj",
            non_interactive=True,
            codex_bypass=False,
            task_id="t1",
        )
