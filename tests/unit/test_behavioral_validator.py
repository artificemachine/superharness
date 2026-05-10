"""Unit tests for Iter 5: BehavioralValidator — HTTP assertion runner."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from superharness.engine.behavioral_validator import (
    BehavioralStep,
    BehavioralValidator,
)


class TestBehavioralStep:
    def test_passes_on_expected_status(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"{}"

        with patch("urllib.request.urlopen", return_value=mock_resp):
            step = BehavioralStep(action="GET /api/status", expect_status=200)
            result = step.run("http://localhost:8787")
        assert result.passed is True
        assert result.status_code == 200

    def test_fails_on_wrong_status(self, monkeypatch):
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url="", code=500, msg="err", hdrs=None, fp=None  # type: ignore
        )):
            step = BehavioralStep(action="GET /api/status", expect_status=200)
            result = step.run("http://localhost:8787")
        assert result.passed is False
        assert "500" in result.finding

    def test_fails_when_json_key_missing(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"other": "value"}).encode()

        with patch("urllib.request.urlopen", return_value=mock_resp):
            step = BehavioralStep(
                action="GET /api/tasks", expect_status=200, expect_json_key="tasks"
            )
            result = step.run("http://localhost:8787")
        assert result.passed is False
        assert "tasks" in result.finding

    def test_passes_when_json_key_present(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"tasks": []}).encode()

        with patch("urllib.request.urlopen", return_value=mock_resp):
            step = BehavioralStep(
                action="GET /api/tasks", expect_status=200, expect_json_key="tasks"
            )
            result = step.run("http://localhost:8787")
        assert result.passed is True


class TestBehavioralValidatorParsing:
    def test_parse_plan_extracts_steps(self):
        contract = {
            "behavioral_assertions": [
                {"action": "GET /api/status", "expect_status": 200},
                {"action": "GET /api/tasks", "expect_status": 200, "expect_json_key": "tasks"},
            ]
        }
        validator = BehavioralValidator.parse_plan(contract)
        assert len(validator.steps) == 2
        assert validator.steps[0].action == "GET /api/status"
        assert validator.steps[1].expect_json_key == "tasks"

    def test_empty_assertions_produces_no_steps(self):
        validator = BehavioralValidator.from_locked_contract({})
        assert validator.steps == []

    def test_from_locked_contract_accepts_json_string(self):
        contract = json.dumps({
            "behavioral_assertions": [
                {"action": "GET /api/status", "expect_status": 200}
            ]
        })
        validator = BehavioralValidator.from_locked_contract(contract)
        assert len(validator.steps) == 1

    def test_all_pass_verdict_is_passed(self, monkeypatch):
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        mock_resp.read.return_value = b"{}"

        contract = {
            "behavioral_assertions": [
                {"action": "GET /api/status", "expect_status": 200},
            ]
        }
        validator = BehavioralValidator.from_locked_contract(contract)
        with patch("urllib.request.urlopen", return_value=mock_resp):
            verdict = validator.run()
        assert verdict.passed is True
        assert verdict.findings == []

    def test_one_fail_verdict_is_not_passed(self, monkeypatch):
        import urllib.error
        contract = {
            "behavioral_assertions": [
                {"action": "GET /api/status", "expect_status": 200},
            ]
        }
        validator = BehavioralValidator.from_locked_contract(contract)
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url="", code=503, msg="down", hdrs=None, fp=None  # type: ignore
        )):
            verdict = validator.run()
        assert verdict.passed is False
        assert len(verdict.findings) == 1
