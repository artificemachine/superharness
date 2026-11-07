"""Hermes as an orchestrator runtime and as an opt-in routing target.

Mirrors the Pi contract: Hermes joins the orchestrator chain, runs the
decomposition prompt with the tool-less `safe` toolset, must return the
routing schema, and is only chosen as an owner when the task carries the
exact `agent:hermes` tag. No test here calls a real model.
"""

from __future__ import annotations

import json

import pytest

from superharness.engine import orchestrator
from superharness.engine.orchestrator import (
    Orchestrator,
    _build_agent_argv,
    _build_orchestrator_chain,
    _normalize_orchestrator_stdout,
)

_VALID = {
    "owner": "hermes",
    "tier": "standard",
    "effort": "low",
    "decompose": False,
    "rationale": "single chore",
    "subtasks": [],
}


def test_hermes_is_in_the_orchestrator_chain():
    assert "hermes" in {binary for binary, _model, _label in _build_orchestrator_chain()}


def test_hermes_orchestrator_argv_is_one_shot_and_tool_less():
    argv = _build_agent_argv("hermes", "deepseek/deepseek-v4-pro", "fixture prompt")
    assert argv == [
        "hermes", "chat", "-Q", "--oneshot", "--ignore-rules",
        "-t", "safe", "-m", "deepseek/deepseek-v4-pro", "-q", "fixture prompt",
    ]


def test_hermes_stdout_drops_banner_lines_before_the_json():
    stdout = (
        "⚠️  Normalized model 'deepseek/deepseek-v4-pro' to 'deepseek-v4-pro' for \n"
        "deepseek.\n"
        + json.dumps(_VALID)
        + "\n"
    )
    assert json.loads(_normalize_orchestrator_stdout("hermes", stdout)) == _VALID


@pytest.mark.parametrize(
    "stdout",
    [
        "no json here",
        "[1, 2]",
        json.dumps({**_VALID, "owner": "nobody"}),
        json.dumps({k: v for k, v in _VALID.items() if k != "tier"}),
    ],
)
def test_hermes_stdout_without_a_valid_routing_payload_fails_closed(stdout):
    with pytest.raises(ValueError):
        _normalize_orchestrator_stdout("hermes", stdout)


def test_routing_payload_accepts_hermes_as_owner_for_every_runtime():
    orchestrator._validate_routing_payload(_VALID)


def _route_with(monkeypatch, tmp_path, task):
    monkeypatch.setattr(
        Orchestrator, "_call_orchestrator_model", lambda self, prompt: json.dumps(_VALID)
    )
    return Orchestrator(str(tmp_path)).route(task)


def test_hermes_owner_without_opt_in_falls_back_to_task_owner(monkeypatch, tmp_path):
    plan = _route_with(monkeypatch, tmp_path, {"id": "t", "title": "chore", "owner": "codex-cli"})
    assert plan.owner == "codex-cli"
    assert "agent:hermes" in plan.rationale


def test_hermes_owner_with_exact_opt_in_is_kept(monkeypatch, tmp_path):
    plan = _route_with(
        monkeypatch, tmp_path, {"id": "t", "title": "chore agent:hermes", "owner": "codex-cli"}
    )
    assert plan.owner == "hermes"


def test_decompose_prompt_offers_hermes_as_an_owner(tmp_path):
    prompt = Orchestrator(str(tmp_path))._build_decompose_prompt({"id": "t", "title": "x"})
    assert '"owner": "claude-code | codex-cli | gemini-cli | opencode | pi | hermes"' in prompt
    assert "agent:hermes" in prompt


def test_smart_dispatch_routes_the_exact_hermes_tag_only():
    from superharness.engine.smart_dispatch import choose_agent

    assert choose_agent({"title": "route AGENT:HERMES", "owner": "codex-cli"}) == "hermes"
    for title in ("route agent:hermes-x", "route hermes"):
        assert choose_agent({"title": title, "owner": "codex-cli"}) == "codex-cli"


# --- Keychain-backed environment for direct hermes calls ---------------------

def test_keychain_env_adds_the_key_without_logging_it(monkeypatch, caplog):
    from superharness.harnesses import hermes as h

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return type("R", (), {"returncode": 0, "stdout": "kc-fake-value\n"})()

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(h.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(h.subprocess, "run", fake_run)
    env = h.keychain_env({"PATH": "/bin"})
    assert env["DEEPSEEK_API_KEY"] == "kc-fake-value"
    assert env["PATH"] == "/bin"
    assert calls[0][:1] == ["security"] and "env:DEEPSEEK_API_KEY" in calls[0] and "-w" in calls[0]
    assert "kc-fake-value" not in caplog.text


def test_keychain_env_keeps_an_exported_key_and_skips_lookup(monkeypatch):
    from superharness.harnesses import hermes as h

    monkeypatch.setattr(h.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(h.subprocess, "run", lambda *a, **k: pytest.fail("lookup ran"))
    env = h.keychain_env({"DEEPSEEK_API_KEY": "already"})
    assert env["DEEPSEEK_API_KEY"] == "already"


def test_keychain_env_without_security_or_entry_leaves_env_unchanged(monkeypatch):
    from superharness.harnesses import hermes as h

    monkeypatch.setattr(h.shutil, "which", lambda name: None)
    assert "DEEPSEEK_API_KEY" not in h.keychain_env({"PATH": "/bin"})

    monkeypatch.setattr(h.shutil, "which", lambda name: "/usr/bin/security")
    monkeypatch.setattr(
        h.subprocess, "run",
        lambda *a, **k: type("R", (), {"returncode": 44, "stdout": ""})(),
    )
    assert "DEEPSEEK_API_KEY" not in h.keychain_env({"PATH": "/bin"})


def test_orchestrator_passes_keychain_env_to_hermes_only(monkeypatch, tmp_path):
    from superharness.harnesses import hermes as h

    seen = {}

    def fake_run(argv, **kwargs):
        seen[argv[0]] = kwargs.get("env")
        return type("R", (), {"returncode": 1, "stdout": "", "stderr": ""})()

    monkeypatch.setattr(h, "keychain_env", lambda base=None: {"DEEPSEEK_API_KEY": "k"})
    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)
    monkeypatch.setattr(
        orchestrator, "_shuffle_chain",
        lambda: [("hermes", "m", "Hermes max"), ("codex", "m", "Codex max")],
    )
    Orchestrator(str(tmp_path))._call_orchestrator_model("p")
    assert seen["hermes"] == {"DEEPSEEK_API_KEY": "k"}
    assert seen["codex"] is None
