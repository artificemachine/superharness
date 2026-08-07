"""Probe-based model discovery.

Iteration 3 of PLAN-dynamic-model-selection.md.

CLIs without a native model-list command (codex, claude, gemini) are probed:
for each candidate in the manifest's ``accept`` chain, dispatch a one-token
call with that model and observe the exit code + stderr.  rc=0 → discovered;
a "not supported"-class error → rejected; anything else → unknown.

Never raises, never exceeds ``budget_seconds``, and never leaves zombie
processes (each probe uses subprocess.run with its own timeout).
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from superharness.engine.model_discovery import DiscoveredModel

# Per-agent probe command templates. `{model}` is replaced with the
# candidate id. The prompt is deliberately a one-token reply so probe
# cost is minimal.
PROBE_COMMANDS: dict[str, list[str]] = {
    "codex-cli": ["codex", "exec", "--model", "{model}", "reply with the single word ok"],
    "claude-code": ["claude", "-p", "--model", "{model}", "reply with the single word ok"],
    "gemini-cli": ["gemini", "-p", "-m", "{model}", "reply with the single word ok"],
}

_PROBE_TIMEOUT_MIN_SECONDS = 1.0

# Stderr substrings that identify an auth/model-mismatch rejection as
# opposed to a transient failure.  Model name is interpolated in.
_REJECT_PATTERNS = (
    "not supported",
    "invalid model",
    "model not found",
    "no such model",
    "does not exist",
)


@dataclass
class ProbeDiscovery:
    """Probe an accept chain until a working model is found."""

    agent: str
    accept_chain: list[str]
    auth_mode: str = "unknown"
    budget_seconds: float = 5.0
    bin_path: str | None = None

    def run(self) -> list[DiscoveredModel]:
        """Probe candidates in order; return DiscoveredModel for acceptances.

        Candidates rejected or unknown are skipped. An empty chain returns
        an empty list immediately. Never raises.
        """
        if not self.accept_chain:
            return []
        start = time.monotonic()
        found: list[DiscoveredModel] = []
        now = datetime.now(timezone.utc)

        for model in self.accept_chain:
            remaining = self.budget_seconds - (time.monotonic() - start)
            if remaining <= 0:
                break
            timeout = max(_PROBE_TIMEOUT_MIN_SECONDS, remaining / len(self.accept_chain))
            verdict, stdout, stderr = self._probe(model, timeout)
            if verdict == "discovered":
                found.append(
                    DiscoveredModel(
                        id=model,
                        label=model,
                        source="probe",
                        auth_mode=self.auth_mode,
                        probed_at=now,
                    )
                )
                break  # first working model wins (accept chain order)
        return found

    # ------------------------------------------------------------------
    # Classification (unit-tested without subprocess)
    # ------------------------------------------------------------------

    def _classify(self, model: str, returncode: int, stdout: str, stderr: str) -> str:
        """Classify a probe result: 'discovered' | 'rejected' | 'unknown'."""
        if returncode == 0:
            return "discovered"
        combined = (stderr or "") + " " + (stdout or "")
        lowered = combined.lower()
        for pattern in _REJECT_PATTERNS:
            if pattern in lowered:
                return "rejected"
        return "unknown"

    # ------------------------------------------------------------------
    # Subprocess invocation (integration-tested)
    # ------------------------------------------------------------------

    def _probe(self, model: str, timeout: float) -> tuple[str, str, str]:
        """Run one probe dispatch; returns (verdict, stdout, stderr)."""
        cmd_template = PROBE_COMMANDS.get(self.agent)
        if cmd_template is None:
            return "unknown", "", ""
        cmd = [part.replace("{model}", model) for part in cmd_template]
        if self.bin_path:
            cmd = [self.bin_path] + cmd[1:]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "unknown", "", ""
        except (FileNotFoundError, OSError):
            return "unknown", "", ""
        return (
            self._classify(model, result.returncode, result.stdout, result.stderr),
            result.stdout,
            result.stderr,
        )
