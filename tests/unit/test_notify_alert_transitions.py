"""notify alert transitions and delivery semantics.

- A sustained outage alerts once per cooldown, not once per run.
- An alert is recorded as sent only after a backend confirms delivery;
  a failed or raising backend leaves the alert retryable and exits 12.
- A watcher that comes back after an alerted outage sends one recovery
  notification, retried until delivered.
- A dry run never consumes an alert.
- The desktop notification never interpolates the message into AppleScript.
"""

from __future__ import annotations

import subprocess

import pytest

from superharness.commands import notify
from superharness.engine import relay_client


@pytest.fixture
def project(tmp_path):
    project_dir = tmp_path / "proj"
    (project_dir / ".superharness").mkdir(parents=True)
    return project_dir


class _Backend:
    def __init__(self):
        self.messages: list[str] = []
        self.results: list[object] = []

    def __call__(self, text):
        self.messages.append(text)
        result = self.results.pop(0) if self.results else (True, "relay")
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def env(project, monkeypatch):
    """Linux, no desktop/webhook tools, no retry alerts, scripted health."""
    health = {"value": (False, "watcher not loaded")}
    backend = _Backend()
    monkeypatch.setattr(notify.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notify.shutil, "which", lambda _name: None)
    monkeypatch.setattr(notify, "_retry_high_ids", lambda *_a: [])
    monkeypatch.setattr(notify, "_watcher_health", lambda *_a: health["value"])
    monkeypatch.setattr(relay_client, "dispatch_notification", backend)
    return health, backend


def _run(project, *extra) -> int:
    argv = ["-p", str(project), "--watcher-down-streak", "1", *extra]
    with pytest.raises(SystemExit) as exc:
        notify.main(argv)
    return exc.value.code


def _state(project) -> dict[str, str]:
    path = project / ".superharness" / "notify.state"
    return dict(
        line.split("=", 1) for line in path.read_text().splitlines() if "=" in line
    )


def test_sustained_outage_alerts_once_within_cooldown(project, env):
    _health, backend = env

    codes = [_run(project) for _ in range(6)]

    assert len(backend.messages) == 1
    assert codes[0] == 10
    assert codes[1:] == [11] * 5


def test_failed_delivery_is_not_recorded_and_is_retried(project, env):
    _health, backend = env
    backend.results = [(False, "")]

    first = _run(project)

    assert first == 12
    assert _state(project)["LAST_SENT_EPOCH"] == "0"

    second = _run(project)

    assert second == 10
    assert len(backend.messages) == 2


def test_raising_backend_counts_as_failed_delivery(project, env):
    _health, backend = env
    backend.results = [RuntimeError("relay down")]

    assert _run(project) == 12
    assert _state(project)["LAST_SENT_EPOCH"] == "0"


def test_recovery_sends_one_notification(project, env):
    health, backend = env
    assert _run(project) == 10

    health["value"] = (True, "watcher healthy")
    assert _run(project) == 10
    assert _run(project) == 0

    assert len(backend.messages) == 2
    assert "recovered" in backend.messages[1]


def test_failed_recovery_notification_is_retried(project, env):
    health, backend = env
    assert _run(project) == 10

    health["value"] = (True, "watcher healthy")
    backend.results = [(False, "")]
    assert _run(project) == 12
    assert _run(project) == 10

    assert [("recovered" in m) for m in backend.messages] == [False, True, True]


def test_no_recovery_notification_without_a_prior_alert(project, env):
    health, backend = env
    health["value"] = (True, "watcher healthy")

    assert _run(project) == 0
    assert backend.messages == []


def test_dry_run_does_not_consume_the_alert(project, env):
    _health, backend = env

    assert _run(project, "--dry-run") == 10
    assert backend.messages == []
    assert _run(project) == 10
    assert len(backend.messages) == 1


def test_desktop_notification_passes_message_as_argument(project, monkeypatch):
    # The quote rides in the outage detail, not the path: Windows forbids
    # '"' in directory names, and the message carries both the same way.
    hostile = 'down "x" & do shell script "true"'
    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(notify.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        notify.shutil,
        "which",
        lambda name: "/usr/bin/osascript" if name == "osascript" else None,
    )
    monkeypatch.setattr(notify, "_retry_high_ids", lambda *_a: [])
    monkeypatch.setattr(notify, "_watcher_health", lambda *_a: (False, hostile))
    monkeypatch.setattr(relay_client, "dispatch_notification", lambda _t: (False, ""))
    monkeypatch.setattr(notify.subprocess, "run", fake_run)

    assert _run(project) == 10

    osascript = [c for c in calls if c[0] == "osascript"]
    assert len(osascript) == 1
    scripts = [osascript[0][i + 1] for i, a in enumerate(osascript[0]) if a == "-e"]
    assert not any(hostile in s for s in scripts)
    assert hostile in osascript[0][-1]
