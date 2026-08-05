"""Tests for shux talk — session-name-addressed inter-agent threads."""

from __future__ import annotations

import json

import pytest

from superharness.commands import talk
from superharness.engine.errors import UsageError


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """Isolated project with legacy in-project state DB and talk registry."""
    proj = tmp_path / "proj"
    (proj / ".superharness").mkdir(parents=True)
    monkeypatch.setenv("SUPERHARNESS_TALK_DIR", str(tmp_path / "talk"))
    monkeypatch.delenv("SUPERHARNESS_STATE_PROJECT", raising=False)
    return proj


def _as(monkeypatch, tmp_path, who: str):
    monkeypatch.setenv("SUPERHARNESS_TALK_SELF", str(tmp_path / f"self-{who}"))


def test_register_writes_identity_and_session_record(project, tmp_path, monkeypatch):
    _as(monkeypatch, tmp_path, "alpha")
    assert talk.cmd_register(str(project), "alpha", "claude-code") == 0

    session_file = tmp_path / "talk" / "sessions" / "alpha.json"
    record = json.loads(session_file.read_text())
    assert record["name"] == "alpha"
    assert record["agent"] == "claude-code"
    assert (tmp_path / "self-alpha").read_text().split() == ["alpha", "claude-code"]


def test_send_show_roundtrip_and_thread_stays_open(
    project, tmp_path, monkeypatch, capsys
):
    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_register(str(project), "alpha", "claude-code")
    _as(monkeypatch, tmp_path, "beta")
    talk.cmd_register(str(project), "beta", "codex-cli")

    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_send(str(project), "beta", "ping from alpha")
    _as(monkeypatch, tmp_path, "beta")
    talk.cmd_send(str(project), "alpha", "pong from beta")
    capsys.readouterr()

    talk.cmd_show(str(project), "alpha")
    out = capsys.readouterr().out
    assert "alpha: ping from alpha" in out
    assert "beta: pong from beta" in out

    # Same pointer both directions; thread still active after both spoke.
    pair_file = tmp_path / "talk" / "threads" / "alpha~beta.id"
    disc_id = pair_file.read_text().strip()
    assert talk._status(str(project), disc_id) == "active"


def test_inbox_lists_only_threads_where_peer_spoke_last(
    project, tmp_path, monkeypatch, capsys
):
    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_register(str(project), "alpha", "claude-code")
    _as(monkeypatch, tmp_path, "beta")
    talk.cmd_register(str(project), "beta", "codex-cli")

    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_send(str(project), "beta", "unanswered")
    capsys.readouterr()

    # Sender's inbox: empty — self spoke last.
    talk.cmd_inbox(str(project))
    assert capsys.readouterr().out == ""

    # Recipient's inbox: shows the waiting message.
    _as(monkeypatch, tmp_path, "beta")
    talk.cmd_inbox(str(project))
    out = capsys.readouterr().out
    assert "alpha~beta" in out
    assert "unanswered" in out


def test_send_to_unknown_peer_fails(project, tmp_path, monkeypatch):
    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_register(str(project), "alpha", "claude-code")
    with pytest.raises(UsageError, match="unknown session"):
        talk.cmd_send(str(project), "ghost", "hello?")


def test_unregistered_session_cannot_send(project, tmp_path, monkeypatch):
    _as(monkeypatch, tmp_path, "nobody")
    with pytest.raises(UsageError, match="not registered"):
        talk.cmd_send(str(project), "anyone", "hi")


def test_send_rotates_closed_thread(project, tmp_path, monkeypatch, capsys):
    from superharness.engine.discussion import cmd_close

    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_register(str(project), "alpha", "claude-code")
    _as(monkeypatch, tmp_path, "beta")
    talk.cmd_register(str(project), "beta", "codex-cli")

    _as(monkeypatch, tmp_path, "alpha")
    talk.cmd_send(str(project), "beta", "first thread")
    pair_file = tmp_path / "talk" / "threads" / "alpha~beta.id"
    first_id = pair_file.read_text().strip()

    cmd_close(
        discussion_dir=str(project / ".superharness" / "discussions" / first_id),
        outcome="cancelled",
        reason="test rotation",
    )
    capsys.readouterr()

    talk.cmd_send(str(project), "beta", "second thread")
    second_id = pair_file.read_text().strip()
    assert second_id != first_id
    history = (tmp_path / "talk" / "threads" / "alpha~beta.history").read_text()
    assert first_id in history


def test_invalid_names_rejected(project, tmp_path, monkeypatch):
    _as(monkeypatch, tmp_path, "alpha")
    with pytest.raises(UsageError, match="Invalid"):
        talk.cmd_register(str(project), "../evil", "claude-code")
