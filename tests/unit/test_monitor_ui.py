from __future__ import annotations

import importlib.util
import json
import threading
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest


def _load_monitor_module(repo_root: Path):
    script = repo_root / "scripts" / "monitor-ui.py"
    spec = importlib.util.spec_from_file_location("monitor_ui_module", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_project(tmp_path: Path) -> Path:
    project = tmp_path / "proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "\n".join(
            [
                "id: monitor-contract",
                "created: 2026-03-09",
                "goal: \"Monitor\"",
                "tasks: []",
            ]
        )
        + "\n"
    )
    (harness / "ledger.md").write_text("Append-only activity log. Never edit previous entries.\n- [2026-03-09T12:00:00Z] monitor test\n")
    (harness / "inbox.yaml").write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: sample-item",
                "  to: codex-cli",
                "  task: mcp-docs",
                f"  project: {project}",
                "  status: pending",
                "  priority: 1",
                "  retry_count: 0",
                "  max_retries: 3",
            ]
        )
        + "\n"
    )
    return project


def _start_server(module, repo_root: Path, project: Path):
    module.Handler.project_dir = project
    module.Handler.label = module.project_label(project)
    module.Handler.refresh_seconds = 3
    module.Handler.scripts_dir = repo_root / "scripts"
    module.Handler.logdy_port = 8797
    module.Handler.auth_token = f"unit-{uuid.uuid4().hex}"
    module.Handler.logdy_process = None
    try:
        server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    except PermissionError as exc:
        pytest.skip(f"Socket bind not permitted in this environment: {exc}")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    return server, thread, base_url


def _request_json(method: str, url: str, payload: dict | None = None, headers: dict[str, str] | None = None):
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _stop_server(server, thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_monitor_status_returns_contract_and_counts(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {
            "loaded": True,
            "state": "running",
            "last_exit_code": "0",
            "run_interval_seconds": 15,
        },
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "monitor-contract")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["contract_id"] == "monitor-contract"
    assert payload["inbox_counts"]["pending"] == 1
    assert payload["watcher_health"]["level"] == "ok"
    assert any("monitor test" in line for line in payload["ledger_tail"])


def test_monitor_action_rejects_missing_token(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.Handler, "_action", lambda self, action: (_ for _ in ()).throw(AssertionError("should not run")))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "dispatch_print_codex"},
            headers={"Origin": base_url, "Content-Type": "application/json"},
        )
    finally:
        _stop_server(server, thread)

    assert status == 403
    assert payload["error"] == "forbidden"


def test_monitor_action_rejects_cross_origin_with_token(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.Handler, "_action", lambda self, action: (_ for _ in ()).throw(AssertionError("should not run")))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "dispatch_print_codex"},
            headers={
                "Origin": "https://evil.example",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 403
    assert payload["error"] == "forbidden"


def test_monitor_action_accepts_same_origin_with_token(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(module.Handler, "_action", lambda self, action: ({"exit_code": 0, "stdout": action, "stderr": ""}, 200))

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "dispatch_print_codex"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["stdout"] == "dispatch_print_codex"


def test_monitor_action_remove_item_calls_inbox_remove(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: dict[str, object] = {}

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        captured["args"] = args
        captured["timeout"] = timeout
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "remove_item:sample-item"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["stdout"] == "ok"
    args = captured["args"]
    assert isinstance(args, list)
    assert "remove" in args
    assert "--id" in args
    assert "sample-item" in args


def test_monitor_action_watcher_start_installs_and_kickstarts(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    calls: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        calls.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "watcher_start"},
            headers={
                "Origin": base_url,
                "Referer": base_url + "/",
                "Content-Type": "application/json",
                "X-Superharness-Token": module.Handler.auth_token,
            },
        )
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert payload["exit_code"] == 0
    assert len(calls) == 2
    install_call = calls[0]
    kickstart_call = calls[1]
    assert "install-launchd-inbox-watcher.sh" in " ".join(install_call)
    assert "--interval" in install_call
    assert "15" in install_call
    assert "--confirm-non-interactive" in install_call
    assert "--confirm-skip-permissions" in install_call
    assert "--launcher-timeout" in install_call
    assert "180" in install_call
    assert kickstart_call[:3] == ["launchctl", "kickstart", "-k"]


def test_monitor_main_rejects_non_loopback_host(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    with pytest.raises(SystemExit, match="loopback-only"):
        import sys

        argv = sys.argv
        sys.argv = [
            "monitor-ui.py",
            "--project",
            str(project),
            "--host",
            "0.0.0.0",
        ]
        try:
            module.main()
        finally:
            sys.argv = argv


def test_monitor_helpers_parse_runtime_and_inbox(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    class _RunResult:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _RunResult(
            0,
            "state = running\nlast exit code = 0\nrun interval = 15 seconds\n",
        ),
    )
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is True
    assert runtime["state"] == "running"
    assert runtime["last_exit_code"] == "0"
    assert runtime["run_interval_seconds"] == 15

    inbox = project / ".superharness" / "inbox.yaml"
    items = module.inbox_items(inbox)
    assert len(items) == 1
    assert items[0]["id"] == "sample-item"
    assert module.inbox_counts(inbox)["pending"] == 1
    assert module.parse_utc_timestamp("2026-03-12T00:00:00Z") is not None
    assert module.parse_utc_timestamp("invalid") is None


def test_monitor_watcher_health_branches(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    now = "2026-03-12T00:10:00Z"

    not_loaded = module.watcher_health(
        {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
        [],
        now,
    )
    assert not_loaded["level"] == "bad"

    idle_ok = module.watcher_health(
        {"loaded": True, "state": "not running", "last_exit_code": "0", "run_interval_seconds": 15},
        [],
        now,
    )
    assert idle_ok["level"] == "ok"

    active_warn = module.watcher_health(
        {"loaded": True, "state": "active", "last_exit_code": "0", "run_interval_seconds": 15},
        [{"status": "stale"}, {"status": "failed"}],
        now,
    )
    assert active_warn["level"] == "warn"

    unknown_state = module.watcher_health(
        {"loaded": True, "state": "throttled", "last_exit_code": "5", "run_interval_seconds": 0},
        [],
        now,
    )
    assert unknown_state["level"] == "warn"

    aging_pending = module.watcher_health(
        {"loaded": True, "state": "running", "last_exit_code": "7", "run_interval_seconds": 0},
        [{"status": "pending", "created_at": "2026-03-12T00:00:00Z"}],
        "2026-03-12T00:20:01Z",
    )
    assert aging_pending["level"] == "warn"
    assert aging_pending["oldest_pending_age_seconds"] > 300


def test_monitor_config_and_pending_approvals(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    handoff_dir = project / ".superharness" / "handoffs"
    md = project / ".superharness" / "handoffs" / "report.md"
    md.write_text("# Report\n")
    (handoff_dir / "one.yaml").write_text(
        "\n".join(
            [
                "task: t1",
                "status: pending_user_approval",
                "markdown_report: .superharness/handoffs/report.md",
                "approval_gate:",
                "  required: true",
                "  approved_by_user: false",
            ]
        )
        + "\n"
    )

    approvals = module.pending_approvals(handoff_dir)
    assert len(approvals) == 1
    assert approvals[0]["task"] == "t1"
    assert approvals[0]["required"] is True

    cfg = project / ".superharness" / "watcher.yaml"
    cfg.write_text(
        "\n".join(
            [
                f"watcher_project: \"{project}\"",
                "interval_seconds: 20",
                "recover_timeout_minutes: 8",
                "recover_action: retry",
                "launcher_timeout_seconds: 77",
                "target: codex-cli",
                "codex_bypass: true",
            ]
        )
        + "\n"
    )
    parsed = module.watcher_config(project)
    assert parsed["interval_seconds"] == 20
    assert parsed["recover_timeout_minutes"] == 8
    assert parsed["recover_action"] == "retry"
    assert parsed["launcher_timeout_seconds"] == 77
    assert parsed["target"] == "codex-cli"
    assert parsed["codex_bypass"] is True

    monkeypatch.setattr(module.shutil, "which", lambda _: None)
    assert module.contract_id(project / ".superharness" / "contract.yaml") == ""


def test_monitor_action_retry_and_stop_paths(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    inbox = project / ".superharness" / "inbox.yaml"
    inbox.write_text(
        "\n".join(
            [
                "# Delegation inbox",
                "# status: pending|launched|running|done|failed|stale",
                "",
                "- id: retry-me",
                "  status: stale",
                "  task: t1",
                f"  project: {project}",
                "  to: codex-cli",
                "- id: stop-me",
                "  status: launched",
                "  task: t2",
                f"  project: {project}",
                "  to: codex-cli",
                "  pid: 999999",
                "- id: wrong-retry",
                "  status: done",
                "  task: t3",
                f"  project: {project}",
                "  to: codex-cli",
            ]
        )
        + "\n"
    )

    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):  # noqa: ANN001, ANN202
        captured.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)
    monkeypatch.setattr(module.os, "kill", lambda *args, **kwargs: None)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "scripts"

    h = module.Handler.__new__(module.Handler)
    retry_ok, status_ok = h._action("retry_item:retry-me")
    assert status_ok == 200
    assert retry_ok["stdout"] == "ok"

    retry_missing, status_missing = h._action("retry_item:missing")
    assert status_missing == 404
    assert "item not found" in retry_missing["error"]

    retry_bad, status_bad = h._action("retry_item:wrong-retry")
    assert status_bad == 400
    assert "cannot retry from status" in retry_bad["error"]

    stop_ok, status_stop = h._action("stop_item:stop-me")
    assert status_stop == 200
    assert stop_ok["stdout"] == "ok"

    unsupported, status_unsup = h._action("unsupported")
    assert status_unsup == 400
    assert "unsupported action" in unsupported["error"]
    assert any("set_status" in " ".join(cmd) for cmd in captured)
