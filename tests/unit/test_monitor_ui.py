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
    monkeypatch.setattr(module, "watcher_state", lambda label: "running")
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
