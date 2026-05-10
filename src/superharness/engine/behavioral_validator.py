"""Behavioral validator — HTTP-driven assertion runner.

Reads `behavioral_assertions` from the locked contract and exercises
the running superharness dashboard (or any HTTP service) to verify
end-to-end flows at milestone boundaries.

Contract assertion format:
    behavioral_assertions:
      - action: GET /api/status
        expect_status: 200
      - action: GET /api/tasks
        expect_status: 200
        expect_json_key: tasks

Usage:
    validator = BehavioralValidator.from_locked_contract(locked_contract_json, base_url)
    verdict = validator.run()
    verdict.passed  # True/False
    verdict.steps   # list of step results
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StepResult:
    action: str
    passed: bool
    finding: str = ""
    status_code: int = 0


@dataclass
class BehavioralVerdict:
    passed: bool
    steps: list[StepResult]

    @property
    def findings(self) -> list[str]:
        return [s.finding for s in self.steps if not s.passed]


@dataclass
class BehavioralStep:
    action: str          # "GET /path" or "POST /path"
    expect_status: int
    expect_json_key: str | None = None
    body: dict[str, Any] | None = None

    def run(self, base_url: str) -> StepResult:
        try:
            import urllib.request
            import urllib.error

            parts = self.action.split(" ", 1)
            method = parts[0].upper() if len(parts) == 2 else "GET"
            path = parts[1] if len(parts) == 2 else parts[0]
            url = f"{base_url.rstrip('/')}{path}"

            data = json.dumps(self.body).encode() if self.body else None
            req = urllib.request.Request(url, data=data, method=method)
            if data:
                req.add_header("Content-Type", "application/json")

            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = resp.status
                    body_bytes = resp.read()
            except urllib.error.HTTPError as e:
                status = e.code
                body_bytes = b""

            if status != self.expect_status:
                return StepResult(
                    action=self.action,
                    passed=False,
                    finding=f"Expected HTTP {self.expect_status}, got {status}",
                    status_code=status,
                )

            if self.expect_json_key:
                try:
                    parsed = json.loads(body_bytes)
                    if self.expect_json_key not in parsed:
                        return StepResult(
                            action=self.action,
                            passed=False,
                            finding=f"JSON key '{self.expect_json_key}' missing in response",
                            status_code=status,
                        )
                except (json.JSONDecodeError, TypeError):
                    return StepResult(
                        action=self.action,
                        passed=False,
                        finding="Response is not valid JSON",
                        status_code=status,
                    )

            return StepResult(action=self.action, passed=True, status_code=status)

        except Exception as exc:
            return StepResult(action=self.action, passed=False, finding=str(exc))


class BehavioralValidator:
    """Run behavioral assertions from a locked contract against a live service."""

    def __init__(self, steps: list[BehavioralStep], base_url: str) -> None:
        self.steps = steps
        self.base_url = base_url

    @classmethod
    def parse_plan(cls, contract: dict[str, Any]) -> "BehavioralValidator":
        """Parse behavioral_assertions from a contract dict (for testing)."""
        return cls.from_locked_contract(contract, base_url="http://localhost:8787")

    @classmethod
    def from_locked_contract(
        cls,
        locked_contract: dict[str, Any] | str,
        base_url: str = "http://localhost:8787",
    ) -> "BehavioralValidator":
        if isinstance(locked_contract, str):
            locked_contract = json.loads(locked_contract)
        assertions: list[dict[str, Any]] = locked_contract.get("behavioral_assertions") or []
        steps = [
            BehavioralStep(
                action=a["action"],
                expect_status=int(a.get("expect_status", 200)),
                expect_json_key=a.get("expect_json_key"),
                body=a.get("body"),
            )
            for a in assertions
        ]
        return cls(steps=steps, base_url=base_url)

    def run(self) -> BehavioralVerdict:
        results = [step.run(self.base_url) for step in self.steps]
        return BehavioralVerdict(passed=all(r.passed for r in results), steps=results)
