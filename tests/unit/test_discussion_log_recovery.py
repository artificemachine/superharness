"""Tests for Bug S fix: _recover_yaml_from_log() in inbox_dispatch.py.

gemini-cli emits its YAML submission to stdout when write_file is blocked.
_recover_yaml_from_log() scans the launcher log and writes the recovered
YAML to disk so _handle_failure() can mark the item done instead of failed.
"""

import os

import yaml

from superharness.commands.inbox_dispatch import _recover_yaml_from_log


DISC_ID = "discuss-20260522T084340Z-13934-583584528"
ROUND = 2
AGENT = "gemini-cli"

VALID_SUBMISSION: dict = {
    "discussion_id": DISC_ID,
    "round": ROUND,
    "agent": AGENT,
    "verdict": "agree",
    "rationale": "All criteria met.",
    "submitted_at": "2026-05-22T09:25:00Z",
}


def _make_log(tmp_path, content: str) -> str:
    p = tmp_path / "launcher.log"
    p.write_text(content, encoding="utf-8")
    return str(p)


def _submission_path(tmp_path) -> str:
    d = tmp_path / ".superharness" / "discussions" / DISC_ID
    return str(d / f"round-{ROUND}-{AGENT}.yaml")


# ---------------------------------------------------------------------------
# Happy-path: fenced code block
# ---------------------------------------------------------------------------

class TestFencedBlock:
    def test_recovers_yaml_from_fenced_code_block(self, tmp_path):
        block = yaml.dump(VALID_SUBMISSION, allow_unicode=True, default_flow_style=False)
        log = _make_log(
            tmp_path,
            "Some preamble\n```yaml\n" + block + "```\nTrailing garbage\n",
        )
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is True
        assert os.path.isfile(out)
        recovered = yaml.safe_load(open(out).read())
        assert recovered["verdict"] == "agree"
        assert recovered["agent"] == AGENT
        assert recovered["round"] == ROUND

    def test_recovers_yaml_from_yml_fenced_block(self, tmp_path):
        block = yaml.dump(VALID_SUBMISSION, allow_unicode=True, default_flow_style=False)
        log = _make_log(tmp_path, "```yml\n" + block + "```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is True

    def test_creates_parent_directories(self, tmp_path):
        block = yaml.dump(VALID_SUBMISSION, allow_unicode=True, default_flow_style=False)
        log = _make_log(tmp_path, "```yaml\n" + block + "```\n")
        deep = str(tmp_path / "a" / "b" / "c" / "submission.yaml")
        assert _recover_yaml_from_log(log, deep, DISC_ID, ROUND, AGENT) is True
        assert os.path.isfile(deep)


# ---------------------------------------------------------------------------
# Happy-path: raw YAML output (no fenced block)
# ---------------------------------------------------------------------------

class TestRawOutput:
    def test_recovers_yaml_from_raw_output(self, tmp_path):
        raw = yaml.dump(VALID_SUBMISSION, allow_unicode=True, default_flow_style=False)
        log = _make_log(tmp_path, "Error: write_file blocked\n" + raw)
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is True
        assert os.path.isfile(out)

    def test_picks_last_raw_occurrence(self, tmp_path):
        old = dict(VALID_SUBMISSION)
        old["verdict"] = "disagree"
        new = dict(VALID_SUBMISSION)
        new["verdict"] = "agree"
        content = (
            yaml.dump(old) + "\nSome noise\n" + yaml.dump(new)
        )
        log = _make_log(tmp_path, content)
        out = _submission_path(tmp_path)
        _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT)
        recovered = yaml.safe_load(open(out).read())
        assert recovered["verdict"] == "agree"


# ---------------------------------------------------------------------------
# Validation: wrong field values are rejected
# ---------------------------------------------------------------------------

class TestValidation:
    def test_rejects_wrong_discussion_id(self, tmp_path):
        bad = dict(VALID_SUBMISSION, discussion_id="discuss-WRONG")
        block = yaml.dump(bad)
        log = _make_log(tmp_path, "```yaml\n" + block + "```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False
        assert not os.path.exists(out)

    def test_rejects_wrong_agent(self, tmp_path):
        bad = dict(VALID_SUBMISSION, agent="claude-code")
        block = yaml.dump(bad)
        log = _make_log(tmp_path, "```yaml\n" + block + "```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False

    def test_rejects_wrong_round(self, tmp_path):
        bad = dict(VALID_SUBMISSION, round=99)
        block = yaml.dump(bad)
        log = _make_log(tmp_path, "```yaml\n" + block + "```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False

    def test_rejects_missing_verdict(self, tmp_path):
        bad = dict(VALID_SUBMISSION)
        del bad["verdict"]
        block = yaml.dump(bad)
        log = _make_log(tmp_path, "```yaml\n" + block + "```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False

    def test_rejects_empty_verdict(self, tmp_path):
        bad = dict(VALID_SUBMISSION, verdict="")
        block = yaml.dump(bad)
        log = _make_log(tmp_path, "```yaml\n" + block + "```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False


# ---------------------------------------------------------------------------
# Resilience: corrupt / missing input
# ---------------------------------------------------------------------------

class TestResilience:
    def test_corrupt_yaml_block_skipped_raw_fallback_used(self, tmp_path):
        good_raw = yaml.dump(VALID_SUBMISSION)
        log = _make_log(
            tmp_path,
            "```yaml\nnot: valid: yaml: :: garbage\n```\n" + good_raw,
        )
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is True

    def test_missing_log_returns_false(self, tmp_path):
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log("/nonexistent/path.log", out, DISC_ID, ROUND, AGENT) is False

    def test_empty_log_returns_false(self, tmp_path):
        log = _make_log(tmp_path, "")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False

    def test_non_dict_yaml_skipped(self, tmp_path):
        log = _make_log(tmp_path, "```yaml\n- item1\n- item2\n```\n")
        out = _submission_path(tmp_path)
        assert _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT) is False

    def test_prefers_last_valid_fenced_block(self, tmp_path):
        old = dict(VALID_SUBMISSION, verdict="disagree")
        new = dict(VALID_SUBMISSION, verdict="agree")
        log = _make_log(
            tmp_path,
            "```yaml\n" + yaml.dump(old) + "```\n"
            + "```yaml\n" + yaml.dump(new) + "```\n",
        )
        out = _submission_path(tmp_path)
        _recover_yaml_from_log(log, out, DISC_ID, ROUND, AGENT)
        recovered = yaml.safe_load(open(out).read())
        assert recovered["verdict"] == "agree"
