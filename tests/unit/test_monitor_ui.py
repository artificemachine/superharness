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
    script = repo_root / "src" / "superharness" / "scripts" / "monitor-ui.py"
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
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"
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


# ---------------------------------------------------------------------------
# plan_proposals() and _confirm_plan() — direct import coverage
# ---------------------------------------------------------------------------


def _setup_plan_project(tmp_path: Path) -> Path:
    """Project with one plan_proposed task and a matching handoff."""
    project = tmp_path / "plan_proj"
    project.mkdir()
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True, exist_ok=True)
    (harness / "contract.yaml").write_text(
        "id: plan-contract\n"
        "goal: test plan gate\n"
        "tasks:\n"
        "  - id: feature-x\n"
        "    title: Implement feature X\n"
        "    status: plan_proposed\n"
        "    owner: claude-code\n"
        "    summary: Will add feature X to the engine\n"
    )
    (harness / "handoffs" / "feature-x.yaml").write_text(
        "task: feature-x\n"
        "status: plan_proposed\n"
        "summary: Plan to implement feature X by modifying engine/contract.rb\n"
        "plan_gate:\n"
        "  required: true\n"
        "  confirmed_by_user: false\n"
    )
    return project


def test_plan_proposals_returns_plan_proposed_tasks(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    harness = project / ".superharness"

    proposals = module.plan_proposals(harness)

    assert len(proposals) == 1
    p = proposals[0]
    assert p["task"] == "feature-x"
    assert p["title"] == "Implement feature X"
    assert p["from"] == "claude-code"
    assert "feature X" in p["summary"]


def test_plan_proposals_returns_empty_when_no_plan_proposed(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)  # has no plan_proposed tasks
    harness = project / ".superharness"

    proposals = module.plan_proposals(harness)

    assert proposals == []


def test_plan_proposals_returns_empty_when_no_contract(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    harness = tmp_path / ".superharness"
    harness.mkdir()

    proposals = module.plan_proposals(harness)

    assert proposals == []


def test_confirm_plan_updates_contract_and_handoff(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    harness = project / ".superharness"

    result = module._confirm_plan(harness, "feature-x")

    assert result["ok"] is True
    assert result["task"] == "feature-x"
    assert "confirmed_at" in result

    # Contract task must now be todo
    import yaml
    doc = yaml.safe_load((harness / "contract.yaml").read_text())
    task = next(t for t in doc["tasks"] if t["id"] == "feature-x")
    assert task["status"] == "todo"
    assert "plan_confirmed_at" in task

    # Handoff must be updated
    hf = harness / "handoffs" / "feature-x.yaml"
    hdata = yaml.safe_load(hf.read_text())
    assert hdata["status"] == "plan_confirmed"
    assert hdata["plan_gate"]["confirmed_by_user"] is True


def test_confirm_plan_returns_error_for_unknown_task(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    harness = project / ".superharness"

    result = module._confirm_plan(harness, "nonexistent-task")

    assert result["ok"] is False
    assert any("not found" in e for e in result.get("errors", []))


def test_confirm_plan_action_via_api(repo_root, tmp_path, monkeypatch) -> None:
    """confirm_plan:<task_id> action via HTTP API updates contract and handoff."""
    module = _load_monitor_module(repo_root)
    project = _setup_plan_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15},
    )
    monkeypatch.setattr(module, "contract_id", lambda path: "plan-contract")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json(
            "POST",
            base_url + "/api/action",
            payload={"action": "confirm_plan:feature-x"},
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
    assert payload.get("ok") is True


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

    assert module.contract_id(project / ".superharness" / "contract.yaml") == "monitor-contract"


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
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

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


def test_monitor_watcher_runtime_nonzero_exit(repo_root, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)

    class _RunResult:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _RunResult(1, ""),
    )
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is False


def test_monitor_watcher_runtime_unparseable_interval(repo_root, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)

    class _RunResult:
        def __init__(self, returncode: int, stdout: str) -> None:
            self.returncode = returncode
            self.stdout = stdout

    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: _RunResult(0, "state = running\nrun interval = notanumber seconds\n"),
    )
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is True
    assert runtime["run_interval_seconds"] == 0


def test_monitor_watcher_runtime_exception(repo_root, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)

    def _raise(*args, **kwargs):
        raise OSError("subprocess failed")

    monkeypatch.setattr(module.subprocess, "run", _raise)
    runtime = module.watcher_runtime("com.example.test")
    assert runtime["loaded"] is False


def test_monitor_watcher_health_stale_and_failed_backlog(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    now = "2026-03-12T00:10:00Z"

    result = module.watcher_health(
        {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15},
        [{"status": "stale"}, {"status": "failed"}, {"status": "pending"}],
        now,
    )
    assert result["level"] == "warn"
    assert result["stale_count"] == 1
    assert result["failed_count"] == 1


def test_monitor_watcher_health_running_healthy(repo_root) -> None:
    module = _load_monitor_module(repo_root)
    now = "2026-03-12T00:10:00Z"

    result = module.watcher_health(
        {"loaded": True, "state": "running", "last_exit_code": "0", "run_interval_seconds": 15},
        [{"status": "pending"}],
        now,
    )
    assert result["level"] == "ok"
    assert "active" in result["message"]


def test_monitor_contract_id_reads_yaml(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    cid = module.contract_id(project / ".superharness" / "contract.yaml")
    assert cid == "monitor-contract"


def test_monitor_contract_id_missing_file(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    cid = module.contract_id(tmp_path / "nonexistent" / "contract.yaml")
    assert cid == ""


def test_monitor_html_endpoint(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/")
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "superharness monitor" in body
    finally:
        _stop_server(server, thread)


def test_monitor_handoff_md_endpoint(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    report = project / ".superharness" / "handoffs" / "test-report.md"
    report.write_text("# Test Report\nSome content.\n")

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/.superharness/handoffs/test-report.md")
        with urllib.request.urlopen(req, timeout=2) as resp:
            body = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "Test Report" in body
    finally:
        _stop_server(server, thread)


def test_monitor_handoff_md_not_found(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/.superharness/handoffs/nonexistent.md")
        try:
            urllib.request.urlopen(req, timeout=2)
            assert False, "Expected 404"
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    finally:
        _stop_server(server, thread)


def test_monitor_handoff_md_path_traversal(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    monkeypatch.setattr(
        module,
        "watcher_runtime",
        lambda label: {"loaded": False, "state": "", "last_exit_code": "", "run_interval_seconds": 0},
    )

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        req = urllib.request.Request(base_url + "/.superharness/handoffs/../../contract.yaml")
        try:
            urllib.request.urlopen(req, timeout=2)
        except urllib.error.HTTPError as exc:
            assert exc.code in (403, 404)
    finally:
        _stop_server(server, thread)


def test_monitor_action_approve_task(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):
        captured.append(args)
        return {"exit_code": 0, "stdout": "approved", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    result, status = h._action("approve_task:my-task")
    assert status == 200
    assert result["stdout"] == "approved"
    args = captured[0]
    assert "approve" in args
    assert "--task" in args
    assert "my-task" in args


def test_monitor_action_approve_task_empty_id(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    result, status = h._action("approve_task:")
    assert status == 400
    assert "missing task id" in result["error"]


def test_monitor_action_pause_and_resume_item(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):
        captured.append(args)
        return {"exit_code": 0, "stdout": "ok", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)

    result, status = h._action("pause_item:item-1")
    assert status == 200
    pause_args = captured[0]
    assert "set_status" in pause_args
    assert "--to" in pause_args
    idx = pause_args.index("--to")
    assert pause_args[idx + 1] == "paused"

    result, status = h._action("resume_item:item-1")
    assert status == 200
    resume_args = captured[1]
    assert "set_status" in resume_args
    idx = resume_args.index("--to")
    assert resume_args[idx + 1] == "pending"


def test_monitor_action_dispatch_and_recover(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    captured: list[list[str]] = []

    def fake_run_cmd(self, args, timeout=30):
        captured.append(args)
        return {"exit_code": 0, "stdout": "done", "stderr": "", "cmd": " ".join(args)}

    monkeypatch.setattr(module.Handler, "_run_cmd", fake_run_cmd)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)

    result, status = h._action("dispatch_print_codex")
    assert status == 200
    assert "inbox-dispatch.sh" in " ".join(captured[-1])
    assert "--to" in captured[-1]
    assert "codex-cli" in captured[-1]

    result, status = h._action("dispatch_print_claude")
    assert status == 200
    assert "claude-code" in captured[-1]

    result, status = h._action("recover_retry")
    assert status == 200
    assert "inbox-recover-stale.sh" in " ".join(captured[-1])

    result, status = h._action("normalize_stale")
    assert status == 200
    assert "inbox-normalize.sh" in " ".join(captured[-1])


def test_monitor_heartbeat_health_missing(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    result = module.heartbeat_health(project)
    assert result["level"] == "warn"
    assert "missing" in result["message"].lower() or "no heartbeat" in result["message"].lower()


def test_monitor_heartbeat_health_stale(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    import time as _time
    from datetime import datetime, timezone

    stale_time = _time.time() - 600
    stale_ts = datetime.fromtimestamp(stale_time, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(stale_ts + "\n")

    result = module.heartbeat_health(project)
    assert result["level"] == "warn"
    assert "stale" in result["message"].lower()
    assert result["age_seconds"] >= 590


def test_monitor_heartbeat_health_ok(repo_root, tmp_path) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)
    heartbeat = project / ".superharness" / "watcher.heartbeat"

    from datetime import datetime, timezone

    fresh_ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    heartbeat.write_text(fresh_ts + "\n")

    result = module.heartbeat_health(project)
    assert result["level"] == "ok"
    assert result["age_seconds"] < 10


def test_monitor_status_includes_heartbeat(repo_root, tmp_path, monkeypatch) -> None:
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
    monkeypatch.setattr(module, "contract_id", lambda path: "demo")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)

    server, thread, base_url = _start_server(module, repo_root, project)
    try:
        status, payload = _request_json("GET", base_url + "/api/status")
    finally:
        _stop_server(server, thread)

    assert status == 200
    assert "heartbeat" in payload
    assert payload["heartbeat"]["level"] in ("ok", "warn")


def test_monitor_action_stop_item_not_found(repo_root, tmp_path, monkeypatch) -> None:
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    module.Handler.project_dir = project
    module.Handler.scripts_dir = repo_root / "src" / "superharness" / "scripts"

    h = module.Handler.__new__(module.Handler)
    result, status = h._action("stop_item:nonexistent")
    assert status == 404
    assert "item not found" in result["error"]


def test_task_report_contract_summary(repo_root, tmp_path) -> None:
    """task_report returns contract task status and summary."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text(
        "id: c1\ntasks:\n"
        "  - id: my-task\n    owner: claude-code\n    status: done\n"
        "    summary: |\n      Implemented feature X with tests.\n"
    )

    result = module.task_report(project, "my-task", "claude-code")
    assert result["contract_status"] == "done"
    assert "feature X" in result["contract_summary"]


def test_task_report_handoff_and_markdown(repo_root, tmp_path) -> None:
    """task_report returns handoff summary and markdown report content."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-md"
    harness = project / ".superharness"
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (harness / "handoffs" / "2026-03-12-my-task.yaml").write_text(
        "task: my-task\nto: codex-cli\nstatus: done\n"
        "summary: Did the thing.\n"
        "markdown_report: .superharness/handoffs/2026-03-12-my-task.md\n"
    )
    (harness / "handoffs" / "2026-03-12-my-task.md").write_text(
        "# My Task Report\n\nCompleted successfully.\n"
    )

    result = module.task_report(project, "my-task", "codex-cli")
    assert result["handoff_summary"] == "Did the thing."
    assert "Completed successfully" in result["markdown_report"]


def test_task_report_discussion_submission(repo_root, tmp_path) -> None:
    """task_report returns discussion state and agent submission."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-disc"
    harness = project / ".superharness"
    disc_dir = harness / "discussions" / "discuss-test-123"
    disc_dir.mkdir(parents=True)
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (disc_dir / "state.yaml").write_text(
        "id: discuss-test-123\ntopic: Review approach\n"
        "status: active\ncurrent_round: 1\nmax_rounds: 3\n"
        "participants:\n  - claude-code\n  - codex-cli\n"
    )
    (disc_dir / "round-1-claude-code.yaml").write_text(
        "discussion_id: discuss-test-123\nround: 1\nagent: claude-code\n"
        "verdict: partial\nposition: Need more testing.\n"
    )

    result = module.task_report(project, "discuss-test-123/round-1", "claude-code")
    assert result["discussion_topic"] == "Review approach"
    assert result["discussion_status"] == "active"
    assert result["discussion_verdict"] == "partial"
    assert "Need more testing" in result["discussion_position"]


def test_task_report_discussion_all_agents(repo_root, tmp_path) -> None:
    """task_report returns all agent positions when no specific agent match."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-all"
    harness = project / ".superharness"
    disc_dir = harness / "discussions" / "discuss-all-456"
    disc_dir.mkdir(parents=True)
    (harness / "handoffs").mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")
    (disc_dir / "state.yaml").write_text(
        "id: discuss-all-456\ntopic: Multi agent\n"
        "status: active\ncurrent_round: 1\nmax_rounds: 2\n"
    )
    (disc_dir / "round-1-claude-code.yaml").write_text(
        "agent: claude-code\nverdict: agree\nposition: Looks good.\n"
    )
    (disc_dir / "round-1-codex-cli.yaml").write_text(
        "agent: codex-cli\nverdict: disagree\nposition: Needs rework.\n"
    )

    result = module.task_report(project, "discuss-all-456/round-1", "gemini-cli")
    assert "claude-code" in result.get("discussion_position", "")
    assert "codex-cli" in result.get("discussion_position", "")
    assert "Looks good" in result["discussion_position"]
    assert "Needs rework" in result["discussion_position"]


def test_task_report_missing_data(repo_root, tmp_path) -> None:
    """task_report returns minimal dict when no data exists."""
    module = _load_monitor_module(repo_root)
    project = tmp_path / "proj-report-empty"
    harness = project / ".superharness"
    harness.mkdir(parents=True)
    (harness / "contract.yaml").write_text("id: c1\ntasks: []\n")

    result = module.task_report(project, "nonexistent-task", "claude-code")
    assert result["task"] == "nonexistent-task"
    assert result["agent"] == "claude-code"
    assert "contract_summary" not in result
    assert "markdown_report" not in result


# ---------------------------------------------------------------------------
# Port auto-find tests
# ---------------------------------------------------------------------------


def _make_eaddrinuse(errno_code: int = 48) -> OSError:
    import errno as _errno
    exc = OSError(_errno.EADDRINUSE, "Address already in use")
    exc.errno = errno_code
    return exc


def test_monitor_main_auto_finds_free_port(repo_root, tmp_path, monkeypatch) -> None:
    """main() skips occupied ports and starts on the first free one."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    call_log: list[int] = []

    class FakeServer:
        def __init__(self, addr, handler):
            call_log.append(addr[1])
            if addr[1] == 8787:
                raise _make_eaddrinuse()
            self.server_address = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: None)

    import sys
    orig = sys.argv
    sys.argv = ["monitor-ui.py", "--project", str(project), "--no-open"]
    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    finally:
        sys.argv = orig

    assert 8787 in call_log
    assert 8788 in call_log
    assert call_log.index(8788) == call_log.index(8787) + 1


def test_monitor_main_skips_multiple_occupied_ports(repo_root, tmp_path, monkeypatch) -> None:
    """main() skips several occupied ports before finding a free one."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    busy_ports = {8787, 8788, 8789}
    call_log: list[int] = []

    class FakeServer:
        def __init__(self, addr, handler):
            call_log.append(addr[1])
            if addr[1] in busy_ports:
                raise _make_eaddrinuse()
            self.server_address = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: None)

    import sys
    orig = sys.argv
    sys.argv = ["monitor-ui.py", "--project", str(project), "--no-open"]
    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    finally:
        sys.argv = orig

    assert call_log[-1] == 8790
    assert set(call_log[:-1]) == busy_ports


def test_monitor_main_exits_when_all_ports_busy(repo_root, tmp_path, monkeypatch) -> None:
    """main() raises SystemExit when no port in the scan range is free."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    class FakeServer:
        def __init__(self, addr, handler):
            raise _make_eaddrinuse()

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)

    import sys
    orig = sys.argv
    sys.argv = ["monitor-ui.py", "--project", str(project), "--no-open"]
    try:
        with pytest.raises(SystemExit, match="No free port"):
            module.main()
    finally:
        sys.argv = orig


def test_monitor_main_explicit_port_fails_clearly(repo_root, tmp_path, monkeypatch) -> None:
    """Explicit --port does not fall back; exits with a clear error."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    class FakeServer:
        def __init__(self, addr, handler):
            raise _make_eaddrinuse()

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)

    import sys
    orig = sys.argv
    sys.argv = ["monitor-ui.py", "--project", str(project), "--port", "9000", "--no-open"]
    try:
        with pytest.raises(SystemExit, match="9000"):
            module.main()
    finally:
        sys.argv = orig


def test_monitor_main_linux_eaddrinuse(repo_root, tmp_path, monkeypatch) -> None:
    """errno 98 (Linux EADDRINUSE) is also handled by the auto-find logic."""
    module = _load_monitor_module(repo_root)
    project = _setup_project(tmp_path)

    call_log: list[int] = []

    class FakeServer:
        def __init__(self, addr, handler):
            call_log.append(addr[1])
            if addr[1] == 8787:
                raise _make_eaddrinuse(errno_code=98)
            self.server_address = addr

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            pass

    monkeypatch.setattr(module, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(module.webbrowser, "open", lambda url: None)

    import sys
    orig = sys.argv
    sys.argv = ["monitor-ui.py", "--project", str(project), "--no-open"]
    try:
        module.main()
    except SystemExit as exc:
        assert exc.code == 0 or exc.code is None
    finally:
        sys.argv = orig

    assert 8788 in call_log
