"""Tests for Iteration 3 of PLAN-dynamic-model-selection.md.

Covers:
- `ProbeDiscovery` — probe-based model discovery for codex/claude/gemini
- Classification: rc=0 → discovered, "not supported" stderr → rejected,
  timeout → unknown
- Budget enforcement, chaos, e2e with a fake codex shim
"""

from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from superharness.engine.probe_discovery import ProbeDiscovery, PROBE_COMMANDS


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_probe_discovery_instantiates() -> None:
    """Smoke: ProbeDiscovery constructs with required args."""
    p = ProbeDiscovery("codex-cli", ["gpt-5.1-codex-mini"], "chatgpt")
    assert p.agent == "codex-cli"
    assert p.accept_chain == ["gpt-5.1-codex-mini"]
    assert p.auth_mode == "chatgpt"


def test_run_returns_list_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke: run() returns a list even when every candidate fails."""
    p = ProbeDiscovery("codex-cli", ["a", "b"], "unknown", budget_seconds=2.0)

    class _FakeResult:
        returncode = 1
        stderr = "model 'a' is not supported"
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    result = p.run()
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Unit — classification
# ---------------------------------------------------------------------------


def test_classify_success_as_discovered() -> None:
    """Unit: rc=0 classifies as discovered."""
    p = ProbeDiscovery("codex-cli", ["m"], "unknown")
    assert p._classify("m", 0, "ok", "") == "discovered"


def test_classify_not_supported_as_rejected() -> None:
    """Unit: rc!=0 + 'not supported' stderr classifies as rejected."""
    p = ProbeDiscovery("codex-cli", ["m"], "unknown")
    assert (
        p._classify(
            "m",
            1,
            "",
            "ERROR: The 'openai/gpt-5.1-codex-mini' model is not supported",
        )
        == "rejected"
    )


def test_classify_generic_failure_as_unknown() -> None:
    """Unit: rc!=0 without a recognizable reason classifies as unknown."""
    p = ProbeDiscovery("codex-cli", ["m"], "unknown")
    assert p._classify("m", 2, "", "some other error") == "unknown"


# ---------------------------------------------------------------------------
# Integration — mixed accept/reject converges
# ---------------------------------------------------------------------------


def test_probe_converges_to_first_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Integration: chain [rejected, accepted] → returns only the accepted one."""
    rejects = {"model-a", "model-b"}
    p = ProbeDiscovery("codex-cli", ["model-a", "model-b", "model-c"], "unknown", budget_seconds=30)

    def _fake_run(cmd, *a, **k):
        model = cmd[cmd.index("--model") + 1] if "--model" in cmd else "?"
        if model in rejects:
            return _Result(1, "", f"model {model} is not supported")
        return _Result(0, "ok", "")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    found = p.run()
    assert [m.id for m in found] == ["model-c"]
    assert all(m.source == "probe" for m in found)


class _Result:
    def __init__(self, rc, out, err):
        self.returncode = rc
        self.stdout = out
        self.stderr = err


# ---------------------------------------------------------------------------
# State machine — each candidate transitions exactly once
# ---------------------------------------------------------------------------


def test_candidate_transitions_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """State machine: each candidate is probed exactly once (all rejected)."""
    probed: list[str] = []
    p = ProbeDiscovery("codex-cli", ["m1", "m2"], "unknown", budget_seconds=30)

    def _fake_run(cmd, *a, **k):
        model = cmd[cmd.index("--model") + 1]
        probed.append(model)
        return _Result(1, "", "not supported")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    p.run()
    assert probed == ["m1", "m2"]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_signature_and_defaults() -> None:
    """Contract: __init__ signature and budget default."""
    import inspect

    sig = inspect.signature(ProbeDiscovery.__init__)
    params = list(sig.parameters)
    assert params[:4] == ["self", "agent", "accept_chain", "auth_mode"]
    # Default budget is 30s: real agent CLIs take ~10s to boot (measured:
    # codex exec gpt-5.5 ≈ 9.6s), so the old 5s default killed working
    # models as timeouts.
    assert sig.parameters["budget_seconds"].default == 30.0
    assert sig.parameters["auth_mode"].default == "unknown"


def test_probe_commands_cover_three_agents() -> None:
    """Contract: PROBE_COMMANDS defines a probe template for codex/claude/gemini."""
    for agent in ("codex-cli", "claude-code", "gemini-cli"):
        assert agent in PROBE_COMMANDS
        assert "{model}" in PROBE_COMMANDS[agent]


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------


def test_empty_accept_chain_returns_empty() -> None:
    """Regression: empty accept chain → run() returns [] (no probing)."""
    p = ProbeDiscovery("codex-cli", [], "unknown", budget_seconds=1.0)
    assert p.run() == []


# ---------------------------------------------------------------------------
# Chaos
# ---------------------------------------------------------------------------


def test_all_timeouts_return_empty_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chaos: every candidate times out → [] and wall-time ≤ budget * 1.1."""
    p = ProbeDiscovery("codex-cli", ["m1", "m2", "m3"], "unknown", budget_seconds=2.0)

    def _fake_run(cmd, *a, **k):
        raise subprocess.TimeoutExpired(cmd="probe", timeout=5)

    monkeypatch.setattr(subprocess, "run", _fake_run)
    start = time.perf_counter()
    result = p.run()
    elapsed = time.perf_counter() - start
    assert result == []
    assert elapsed <= 2.0 * 1.1


# ---------------------------------------------------------------------------
# Performance — budget enforcement
# ---------------------------------------------------------------------------


def test_probe_respects_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Performance: run() never exceeds budget even with many candidates."""
    chain = [f"m{i}" for i in range(20)]
    p = ProbeDiscovery("codex-cli", chain, "unknown", budget_seconds=1.5)

    def _fake_run(cmd, *a, **k):
        time.sleep(0.2)
        return _Result(1, "", "not supported")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    start = time.perf_counter()
    p.run()
    elapsed = time.perf_counter() - start
    # 20 candidates × 0.2s = 4s without budget; with budget it must cap ~1.5s.
    assert elapsed <= 1.5 * 1.2


def test_unknown_agent_returns_empty() -> None:
    """Chaos: an agent with no probe template yields [] without raising."""
    p = ProbeDiscovery("unknown-agent", ["m1"], "unknown", budget_seconds=1.0)
    assert p.run() == []


def test_binary_missing_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chaos: probe binary missing (FileNotFoundError) → [] without raising."""
    p = ProbeDiscovery("codex-cli", ["m1"], "unknown", budget_seconds=2.0)

    def _fake_run(cmd, *a, **k):
        raise FileNotFoundError("codex not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    assert p.run() == []


# ---------------------------------------------------------------------------
# E2E — fake codex shim
# ---------------------------------------------------------------------------


def test_e2e_fake_codex_rejects_mini_accepts_fallback(tmp_path: Path) -> None:
    """E2E: fake codex rejects gpt-5.1-codex-mini, accepts gpt-5-codex-mini.

    The probe must return only the accepted model.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "#!/bin/bash\n"
        "for arg in \"$@\"; do\n"
        "  if [ \"$arg\" = 'gpt-5.1-codex-mini' ]; then\n"
        "    echo 'model is not supported when using Codex with a ChatGPT account' >&2\n"
        "    exit 1\n"
        "  fi\n"
        "done\n"
        "echo ok\n"
    )
    fake_codex.chmod(0o755)

    p = ProbeDiscovery(
        "codex-cli",
        ["gpt-5.1-codex-mini", "gpt-5-codex-mini"],
        "chatgpt",
        budget_seconds=30,
        bin_path=str(fake_codex),
    )
    found = p.run()
    assert [m.id for m in found] == ["gpt-5-codex-mini"]
    assert all(m.auth_mode == "chatgpt" for m in found)
