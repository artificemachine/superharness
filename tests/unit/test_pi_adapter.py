"""Iteration 6: Pi is eligible at core lifecycle validation gates."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PI_MANIFEST = _REPO_ROOT / "src" / "superharness" / "adapter_manifests" / "pi.yaml"
_MODEL_DOC = _REPO_ROOT / "docs" / "adapter-models.md"
_WORKER_EVIDENCE_HEADING = "### Pi worker activation evidence — 2026-08-26"
_ORCHESTRATOR_EVIDENCE_HEADING = (
    "### Pi orchestrator activation evidence — 2026-08-26"
)
_REVIEWER_DECISION = (
    "Reviewer decision: APPROVE — two independently approved Pi worker runs "
    "reproduced successful exact-scope edits using deepseek/deepseek-v4-flash in "
    "distinct disposable worktrees; both exited 0 with stopReason stop, valid "
    "terminal streams, and verified cleanup."
)
_ORCHESTRATOR_REVIEWER_DECISION = (
    "Reviewer decision: APPROVE — the separately approved Pi live decomposition "
    "at 2026-08-26T17:23:23Z used Pi CLI 0.73.1 with requested and actual "
    "deepseek/deepseek-v4-pro, exited 0 with one assistant message and one "
    "agent_end in a valid bounded stream, returned a complete valid decomposition "
    "with produced-owner set {codex-cli, pi}, ran with --no-tools in a fresh "
    "disposable worktree, left zero modifications, and completed verified cleanup; "
    "the earlier schema-invalid attempt is excluded from evidence."
)
_REQUIRES_POSIX_FIXTURE = pytest.mark.skipif(
    os.name != "posix",
    reason="Pi capture fixtures use POSIX shebang executables",
)


def _worker_evidence_record(document: str) -> str | None:
    """Return one complete sanitized worker record, or ``None``."""
    if document.count(_WORKER_EVIDENCE_HEADING) != 1:
        return None
    record = document.split(_WORKER_EVIDENCE_HEADING, 1)[1].split("\n## ", 1)[0]
    normalized_record = " ".join(record.split())
    required = (
        "Pi CLI version: `0.73.1`",
        "Approved provider/model: `deepseek/deepseek-v4-flash`",
        "2026-08-26T16:20:37Z",
        "`133a9685b268198649324434ba06d52f9ab4918a792fac94dce655fbdc84eb93`",
        "2026-08-26T16:23:02Z",
        "`33af538d4aba0db1c662d1600020f6d2d245ca54a822d00e88c6830bf52f4753`",
        _REVIEWER_DECISION,
    )
    if not all(item in normalized_record for item in required):
        return None
    if record.count("- Run ") != 2:
        return None
    for run_number in (1, 2):
        match = re.search(
            rf"(?ms)^- Run {run_number}:.*?(?=^- Run |^- Reviewer decision:|\Z)",
            record,
        )
        run_record = " ".join(match.group(0).split()) if match else ""
        if not all(
            item in run_record
            for item in (
                "exit `0`",
                "result `pass`",
                "stopReason `stop`",
                "exact file/scope verified",
                "valid terminal stream",
                "cleanup verified",
            )
        ):
            return None
    if re.search(r"(?:^|\s)/(?:Users|home|private|tmp|var)/", record):
        return None
    if any(
        forbidden in record.casefold()
        for forbidden in (
            "raw prompt:",
            "raw output:",
            "credential=",
            "api key",
            "access token",
        )
    ):
        return None
    return record


def _orchestrator_evidence_record(document: str) -> str | None:
    """Return one complete sanitized orchestrator record, or ``None``."""
    if document.count(_ORCHESTRATOR_EVIDENCE_HEADING) != 1:
        return None
    record = document.split(_ORCHESTRATOR_EVIDENCE_HEADING, 1)[1].split(
        "\n## ", 1
    )[0]
    normalized_record = " ".join(record.split())
    required = (
        "2026-08-26T17:23:23Z",
        "Pi CLI version: `0.73.1`",
        "Requested provider/model: `deepseek/deepseek-v4-pro`",
        "Actual provider/model: `deepseek/deepseek-v4-pro`",
        "Prompt SHA-256: `06fb34316c4435b572bba8fe44220590ba73c0b41b44212a26b3c1cc8bd357f9`",
        "Exit: `0`",
        "Assistant messages: `1`",
        "Agent-end events: `1`",
        "Valid bounded stream: `yes`",
        "Complete valid decomposition: `yes`",
        "Produced-owner set: `{codex-cli, pi}`",
        "Tools: `--no-tools`",
        "Fresh disposable worktree: `yes`",
        "Worktree modifications: `0`",
        "Cleanup verified: `yes`",
        _ORCHESTRATOR_REVIEWER_DECISION,
    )
    if not all(item in normalized_record for item in required):
        return None
    if re.search(r"(?:^|\s)/(?:Users|home|private|tmp|var)/", record):
        return None
    if any(
        forbidden in record.casefold()
        for forbidden in (
            "raw prompt:",
            "raw output:",
            "credential=",
            "api key",
            "access token",
        )
    ):
        return None
    return record


def _project(tmp_path):
    project = tmp_path / "pi-lifecycle"
    (project / ".superharness").mkdir(parents=True)
    return project


def _create_task(project, task_id="pi-task", owner="pi", workflow="quick"):
    from superharness.commands.task import create

    assert (
        create(
            project_dir=str(project),
            task_id=task_id,
            title="Pi lifecycle task",
            owner=owner,
            status="todo",
            project_path=str(project),
            workflow=workflow,
            require_tdd=False,
        )
        == 0
    )


def _agent_validation_error(call, capsys):
    with pytest.raises(SystemExit) as exc_info:
        call()
    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    choices = error.partition("(choose from ")[2] or error
    assert "pi" in choices
    assert "prime-agent" not in choices


def _task_owner(project, task_id):
    from superharness.engine import tasks_dao
    from superharness.engine.db import get_connection, init_db

    conn = get_connection(str(project))
    try:
        init_db(conn)
        return tasks_dao.get(conn, task_id).owner
    finally:
        conn.close()


def _set_owner_via_cli(project, owner):
    from superharness.commands.task import main

    main(
        [
            "set-owner",
            "--project",
            str(project),
            "--id",
            "pi-task",
            "--owner",
            owner,
        ]
    )


def test_promoted_pi_has_no_experimental_tier() -> None:
    document = _MODEL_DOC.read_text(encoding="utf-8")
    manifest = yaml.safe_load(_PI_MANIFEST.read_text(encoding="utf-8"))

    assert _worker_evidence_record(document) is not None
    assert "EXPERIMENTAL" not in manifest["description"]
    assert all(
        "experimental" not in tier["capability_tags"]
        for tier in manifest["model_tiers"].values()
    )


def test_worker_evidence_record_is_complete() -> None:
    document = _MODEL_DOC.read_text(encoding="utf-8")

    assert _worker_evidence_record(document) is not None


@pytest.mark.parametrize("failure", ["incomplete", "duplicate"])
def test_incomplete_or_duplicate_worker_evidence_does_not_satisfy_gate(failure) -> None:
    document = _MODEL_DOC.read_text(encoding="utf-8")
    if failure == "incomplete":
        document = document.replace("cleanup verified", "cleanup omitted", 1)
    else:
        record = _WORKER_EVIDENCE_HEADING + document.split(
            _WORKER_EVIDENCE_HEADING, 1
        )[1].split("\n## ", 1)[0]
        document = f"{document}\n{record}\n"

    assert _worker_evidence_record(document) is None


def test_task_create_accepts_pi_owner(tmp_path) -> None:
    project = _project(tmp_path)

    _create_task(project)

    assert _task_owner(project, "pi-task") == "pi"


@pytest.mark.parametrize("owner", ["unknown-agent", "prime-agent"])
def test_task_owner_rejects_unknown_and_inert_manifest(tmp_path, capsys, owner) -> None:
    project = _project(tmp_path)

    _agent_validation_error(
        lambda: _create_task(project, task_id=f"{owner}-task", owner=owner), capsys
    )


def test_task_owner_retains_human_owner_exception(tmp_path) -> None:
    project = _project(tmp_path)

    _create_task(project, task_id="human-task", owner="owner")


def test_task_set_owner_accepts_pi(tmp_path) -> None:
    project = _project(tmp_path)
    _create_task(project, owner="claude-code")

    with pytest.raises(SystemExit) as exc_info:
        _set_owner_via_cli(project, "pi")

    assert exc_info.value.code == 0
    assert _task_owner(project, "pi-task") == "pi"


@pytest.mark.parametrize("owner", ["unknown-agent", "prime-agent"])
def test_task_set_owner_rejects_unknown_and_inert_without_mutation(
    tmp_path, capsys, owner
) -> None:
    project = _project(tmp_path)
    _create_task(project, owner="claude-code")

    _agent_validation_error(lambda: _set_owner_via_cli(project, owner), capsys)

    assert _task_owner(project, "pi-task") == "claude-code"


def test_inbox_enqueue_accepts_todo_pi_task_as_plan_only(tmp_path) -> None:
    project = _project(tmp_path)
    _create_task(project, workflow="implementation")

    from superharness.commands.inbox_enqueue import enqueue_cmd
    from superharness.engine import inbox_dao
    from superharness.engine.db import get_connection, init_db

    assert (
        enqueue_cmd(
            str(project), "pi", "pi-task", "pi-inbox", 2, plan_only=True
        )
        == 0
    )
    conn = get_connection(str(project))
    try:
        init_db(conn)
        row = inbox_dao.get(conn, "pi-inbox")
        assert row.target_agent == "pi"
        assert row.plan_only is True
        assert row.status == "pending"
    finally:
        conn.close()


@pytest.mark.parametrize("target", ["unknown-agent", "prime-agent"])
def test_inbox_target_rejects_unknown_and_inert_manifest(tmp_path, capsys, target) -> None:
    project = _project(tmp_path)

    from superharness.commands.inbox_enqueue import enqueue_cmd

    _agent_validation_error(
        lambda: enqueue_cmd(str(project), target, "pi-task", "pi-inbox", 2), capsys
    )


def test_handoff_accepts_pi_from_and_to(tmp_path) -> None:
    project = _project(tmp_path)
    _create_task(project)

    from superharness.commands.handoff_write import _build_parser, write_handoff

    args = _build_parser().parse_args(
        [
            "--task",
            "pi-task",
            "--phase",
            "report",
            "--from",
            "pi",
            "--to",
            "pi",
            "--outcome",
            "completed",
        ]
    )
    rc, payload = write_handoff(project, args)

    assert rc == 0
    assert payload["from"] == payload["to"] == "pi"


@pytest.mark.parametrize(("from_agent", "to_agent"), [("owner", "pi"), ("pi", "owner")])
def test_handoff_retains_human_owner_in_both_directions(
    tmp_path, from_agent, to_agent
) -> None:
    project = _project(tmp_path)
    _create_task(project)

    from superharness.commands.handoff_write import _build_parser, write_handoff

    args = _build_parser().parse_args(
        [
            "--task",
            "pi-task",
            "--phase",
            "report",
            "--from",
            from_agent,
            "--to",
            to_agent,
            "--outcome",
            "completed",
        ]
    )
    rc, payload = write_handoff(project, args)

    assert rc == 0
    assert payload["from"] == from_agent
    assert payload["to"] == to_agent


@pytest.mark.parametrize("flag", ["--from", "--to"])
@pytest.mark.parametrize("agent", ["unknown-agent", "prime-agent"])
def test_handoff_rejects_unknown_and_inert_manifest(capsys, flag, agent) -> None:
    from superharness.commands.handoff_write import _build_parser

    argv = [
        "--task",
        "pi-task",
        "--phase",
        "report",
        "--from",
        "pi",
        "--to",
        "pi",
        "--outcome",
        "completed",
    ]
    argv[argv.index(flag) + 1] = agent

    _agent_validation_error(lambda: _build_parser().parse_args(argv), capsys)


def test_task_inbox_handoff_roundtrip_uses_pi(tmp_path) -> None:
    project = _project(tmp_path)
    _create_task(project)

    from superharness.commands.handoff_write import _build_parser, write_handoff
    from superharness.commands.inbox_enqueue import enqueue_cmd

    assert enqueue_cmd(str(project), "pi", "pi-task", "pi-roundtrip", 2) == 0
    args = _build_parser().parse_args(
        [
            "--task",
            "pi-task",
            "--phase",
            "report",
            "--from",
            "pi",
            "--to",
            "pi",
            "--outcome",
            "completed",
        ]
    )
    rc, payload = write_handoff(project, args)

    assert rc == 0
    assert payload["from"] == payload["to"] == "pi"


def _pi_orchestrator_text_stream(terminal_text: str) -> str:
    events = [
        {"type": "session", "version": 3, "id": "fixture-orchestrator"},
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "toolCall", "name": "read"}],
                "stopReason": "toolUse",
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "toolResult",
                "content": [{"type": "text", "text": "fixture tool result"}],
            },
        },
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": terminal_text}],
                "stopReason": "stop",
            },
        },
        {"type": "agent_end", "messages": []},
    ]
    return "".join(f"{json.dumps(event)}\n" for event in events)


def _pi_orchestrator_stream(payload: object) -> str:
    return _pi_orchestrator_text_stream(json.dumps(payload))


def _fixture_routing_payload(*, owner: str = "pi") -> dict:
    return {
        "owner": "claude-code",
        "tier": "max",
        "effort": "high",
        "decompose": True,
        "rationale": "fixture decomposition",
        "subtasks": [
            {
                "id": "fixture.st1",
                "title": "Implement fixture worker slice",
                "owner": owner,
                "tier": "standard",
                "effort": "medium",
                "blocked_by": None,
                "estimated_tokens": 1000,
            }
        ],
    }


def _invalid_routing_payloads() -> list[object]:
    valid = _fixture_routing_payload()
    invalid_subtask = dict(valid["subtasks"][0])
    invalid_subtask["owner"] = "unknown-agent"
    incomplete_subtask = dict(valid["subtasks"][0])
    del incomplete_subtask["estimated_tokens"]
    return [
        {},
        {"nonsense": True},
        {**valid, "owner": "unknown-agent"},
        {**valid, "tier": "ultra"},
        {**valid, "effort": "extreme"},
        {**valid, "decompose": "yes"},
        {**valid, "rationale": ["not", "text"]},
        {**valid, "subtasks": "not-a-list"},
        {**valid, "subtasks": []},
        {**valid, "subtasks": ["not-an-object"]},
        {**valid, "subtasks": [incomplete_subtask]},
        {**valid, "subtasks": [invalid_subtask]},
        {**valid, "decompose": False, "subtasks": valid["subtasks"]},
    ]


def test_pi_orchestrator_argv_is_ephemeral_json() -> None:
    from superharness.engine.orchestrator import _build_agent_argv
    from superharness.engine.pi_runtime import build_command

    expected = build_command(
        "fixture prompt",
        model="deepseek/deepseek-v4-pro",
        pi_binary="pi",
        no_tools=True,
    )

    command = _build_agent_argv(
        "pi", "deepseek/deepseek-v4-pro", "fixture prompt"
    )

    assert command == expected
    assert "--no-tools" in command
    assert "--no-tools" not in build_command("worker prompt")


def test_pi_orchestrator_extracts_terminal_text() -> None:
    from superharness.engine.orchestrator import _normalize_orchestrator_stdout

    payload = _fixture_routing_payload()

    assert _normalize_orchestrator_stdout(
        "pi", _pi_orchestrator_stream(payload)
    ) == json.dumps(payload)


def test_pi_orchestrator_terminal_text_state_is_bounded(monkeypatch) -> None:
    from superharness.engine import pi_runtime

    monkeypatch.setattr(pi_runtime, "_MAX_TERMINAL_TEXT_CHARS", 16)

    with pytest.raises(ValueError, match="invalid Pi JSONL terminal stream"):
        pi_runtime.extract_terminal_text(
            _pi_orchestrator_stream({"result": "longer than limit"})
        )


def test_chain_keeps_same_model_on_distinct_runtimes(monkeypatch) -> None:
    from superharness.engine import orchestrator

    monkeypatch.setattr(
        orchestrator,
        "_ORCHESTRATOR_CHAIN",
        [
            ("pi", "shared/model", "Pi shared model"),
            ("opencode", "shared/model", "OpenCode shared model"),
        ],
    )
    monkeypatch.setattr(orchestrator.random, "shuffle", lambda entries: None)
    monkeypatch.setattr(orchestrator, "_orchestrator_scores", {})

    assert {(binary, model) for binary, model, _ in orchestrator._shuffle_chain()} == {
        ("pi", "shared/model"),
        ("opencode", "shared/model"),
    }


def test_same_model_runtime_scores_are_independent(monkeypatch) -> None:
    from superharness.engine import orchestrator

    monkeypatch.setattr(orchestrator, "_orchestrator_scores", {})

    orchestrator._record_orchestrator_score("pi", "shared/model", False)
    orchestrator._record_orchestrator_score("opencode", "shared/model", True)

    assert orchestrator._orchestrator_scores[("pi", "shared/model")][
        "failures"
    ] == 1
    assert orchestrator._orchestrator_scores[("pi", "shared/model")][
        "successes"
    ] == 0
    assert orchestrator._orchestrator_scores[("opencode", "shared/model")][
        "successes"
    ] == 1
    assert orchestrator._orchestrator_scores[("opencode", "shared/model")][
        "failures"
    ] == 0


def test_decomposition_prompt_allows_pi_worker_and_all_owner_examples(
    tmp_path,
) -> None:
    from superharness.engine.orchestrator import Orchestrator

    prompt = Orchestrator(str(tmp_path))._build_decompose_prompt(
        {"id": "fixture", "title": "Fixture decomposition"}
    )
    owner_example = (
        '"owner": "claude-code | codex-cli | gemini-cli | opencode | pi"'
    )

    assert "  pi:" in prompt
    assert prompt.count(owner_example) == 2


def test_pi_fixture_jsonl_normalizes_into_pi_owned_decomposition(
    tmp_path, monkeypatch
) -> None:
    from superharness.engine import orchestrator
    from superharness.engine import pi_runtime

    payload = _fixture_routing_payload()
    calls = []

    def fake_capture(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=_pi_orchestrator_stream(payload),
            stderr="",
        )

    monkeypatch.setattr(
        orchestrator,
        "_shuffle_chain",
        lambda: [("pi", "deepseek/deepseek-v4-pro", "Pi fixture")],
    )
    monkeypatch.setattr(pi_runtime, "capture_pi_command", fake_capture)

    plan = orchestrator.Orchestrator(str(tmp_path)).route(
        {"id": "fixture", "title": "Fixture agent:pi decomposition"}
    )

    assert plan.decompose is True
    assert [subtask["owner"] for subtask in plan.subtasks] == ["pi"]
    assert calls[0][1]["cwd"] == str(tmp_path)


def test_untagged_route_never_promotes_pi_worker(tmp_path, monkeypatch) -> None:
    """Pi stays opt-in even when the orchestrator suggests it for a generic task."""
    from superharness.engine import orchestrator

    payload = _fixture_routing_payload()
    payload["owner"] = "pi"
    monkeypatch.setattr(
        orchestrator.Orchestrator,
        "_call_orchestrator_model",
        lambda _self, _prompt: json.dumps(payload),
    )

    plan = orchestrator.Orchestrator(str(tmp_path)).route(
        {"id": "fixture", "title": "Fixture decomposition", "owner": "codex-cli"}
    )

    assert plan.owner == "codex-cli"
    assert [subtask["owner"] for subtask in plan.subtasks] == ["codex-cli"]


@pytest.mark.parametrize(
    ("subtask_fields", "expected_tier"),
    [
        ({"tier": "mini"}, "mini"),
        ({"tier": "max"}, "max"),
        ({"tier": "max", "model": "haiku-4-5"}, "mini"),
        ({"tier": "max", "model_tier": "invalid"}, "standard"),
    ],
    ids=["mini", "max", "model-precedence", "invalid-model-tier"],
)
def test_pi_decompose_normalizes_subtask_tier(
    tmp_path, monkeypatch, subtask_fields, expected_tier
) -> None:
    from superharness.engine import orchestrator
    from superharness.engine import pi_runtime

    payload = _fixture_routing_payload()
    payload["subtasks"][0].update(subtask_fields)

    monkeypatch.setattr(
        orchestrator,
        "_shuffle_chain",
        lambda: [("pi", "deepseek/deepseek-v4-pro", "Pi fixture")],
    )
    monkeypatch.setattr(
        pi_runtime,
        "capture_pi_command",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=_pi_orchestrator_stream(payload),
            stderr="",
        ),
    )

    result = orchestrator.Orchestrator(str(tmp_path)).decompose(
        {"id": "fixture", "title": "Fixture decomposition"}
    )

    assert result.subtasks[0]["model_tier"] == expected_tier


@pytest.mark.parametrize(
    "pi_stdout",
    [
        "{malformed-jsonl}\n",
        _pi_orchestrator_stream(_fixture_routing_payload()).rsplit("\n", 2)[0]
        + "\n",
        (
            '{"type":"session","version":3,"id":"fixture-error"}\n'
            '{"type":"message_end","message":{"role":"assistant",'
            '"content":[],"stopReason":"error",'
            '"errorMessage":"sensitive fixture marker"}}\n'
            '{"type":"agent_end","messages":[]}\n'
        ),
        _pi_orchestrator_text_stream("sensitive malformed terminal marker"),
        _pi_orchestrator_stream([]),
        *[_pi_orchestrator_stream(payload) for payload in _invalid_routing_payloads()],
        "",
    ],
    ids=[
        "malformed",
        "truncated",
        "embedded-error",
        "terminal-malformed-json",
        "terminal-non-object-json",
        "empty-object",
        "nonsense-object",
        "invalid-owner",
        "invalid-tier",
        "invalid-effort",
        "invalid-decompose-type",
        "invalid-rationale-type",
        "invalid-subtasks-type",
        "decompose-true-empty-subtasks",
        "non-object-subtask",
        "incomplete-subtask",
        "invalid-subtask-owner",
        "decompose-false-nonempty-subtasks",
        "empty",
    ],
)
def test_invalid_pi_orchestrator_output_falls_through_without_raw_leak(
    tmp_path, monkeypatch, caplog, pi_stdout
) -> None:
    from superharness.engine import orchestrator
    from superharness.engine import pi_runtime

    fallback = _fixture_routing_payload(owner="codex-cli")
    pi_result = SimpleNamespace(returncode=0, stdout=pi_stdout, stderr="")
    fallback_result = SimpleNamespace(
        returncode=0,
        stdout=json.dumps(fallback),
        stderr="",
    )
    pi_calls = []
    fallback_calls = []

    def fake_capture(argv, **kwargs):
        pi_calls.append((argv, kwargs))
        return pi_result

    def fake_run(argv, **kwargs):
        fallback_calls.append((argv, kwargs))
        return fallback_result

    monkeypatch.setattr(
        orchestrator,
        "_shuffle_chain",
        lambda: [
            ("pi", "shared/model", "Pi fixture"),
            ("codex", "shared/model", "Codex fixture"),
        ],
    )
    monkeypatch.setattr(
        pi_runtime,
        "capture_pi_command",
        fake_capture,
    )
    monkeypatch.setattr(
        orchestrator.subprocess,
        "run",
        fake_run,
    )
    monkeypatch.setattr(orchestrator, "_orchestrator_scores", {})

    plan = orchestrator.Orchestrator(str(tmp_path)).route(
        {"id": "fixture", "title": "Fixture decomposition"}
    )

    assert [subtask["owner"] for subtask in plan.subtasks] == ["codex-cli"]
    assert pi_calls[0][1]["cwd"] == str(tmp_path)
    assert fallback_calls[0][1]["cwd"] == str(tmp_path)
    assert orchestrator._orchestrator_scores[("pi", "shared/model")][
        "successes"
    ] == 0
    assert orchestrator._orchestrator_scores[("pi", "shared/model")][
        "failures"
    ] == 1
    assert "sensitive fixture marker" not in caplog.text
    assert "sensitive malformed terminal marker" not in caplog.text


def _write_interrupt_pi_fixture(tmp_path: Path, *, descendant: bool) -> Path:
    fixture = tmp_path / "pi-interrupt"
    descendant_block = (
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "Path(os.environ['PI_CAPTURE_DESCENDANT']).write_text(str(child.pid))\n"
        if descendant
        else ""
    )
    fixture.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys, time\n"
        "from pathlib import Path\n"
        "Path(os.environ['PI_CAPTURE_SELF']).write_text(str(os.getpid()))\n"
        f"{descendant_block}"
        "Path(os.environ['PI_CAPTURE_READY']).write_text('ready')\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    fixture.chmod(0o755)
    return fixture


@pytest.mark.parametrize("failure_kind", ["keyboard", "unexpected"])
@_REQUIRES_POSIX_FIXTURE
def test_capture_pi_command_cleans_once_and_restores_handlers_on_exception(
    tmp_path, monkeypatch, failure_kind
) -> None:
    from superharness.engine import pi_runtime

    fixture = _write_interrupt_pi_fixture(tmp_path, descendant=False)
    self_pid = tmp_path / "self.pid"
    ready = tmp_path / "ready"
    monkeypatch.setenv("PI_CAPTURE_SELF", str(self_pid))
    monkeypatch.setenv("PI_CAPTURE_READY", str(ready))
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    real_popen = pi_runtime.subprocess.Popen
    real_terminate = pi_runtime._terminate_process_tree
    spawned = []
    cleanup_calls = []

    def recording_popen(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not ready.exists():
            time.sleep(0.01)
        return proc

    def recording_terminate(proc):
        cleanup_calls.append(proc)
        real_terminate(proc)

    def fail_get(self, *args, **kwargs):
        if failure_kind == "keyboard":
            raise KeyboardInterrupt
        raise RuntimeError("unexpected capture fixture failure")

    monkeypatch.setattr(pi_runtime.subprocess, "Popen", recording_popen)
    monkeypatch.setattr(pi_runtime, "_terminate_process_tree", recording_terminate)
    monkeypatch.setattr(pi_runtime.queue.Queue, "get", fail_get)

    try:
        expected = KeyboardInterrupt if failure_kind == "keyboard" else RuntimeError
        with pytest.raises(expected):
            pi_runtime.capture_pi_command(
                [str(fixture)], cwd=str(tmp_path), timeout_seconds=5
            )

        assert len(cleanup_calls) == 1
        assert spawned[0].returncode is not None
        assert signal.getsignal(signal.SIGTERM) is previous[signal.SIGTERM]
        assert signal.getsignal(signal.SIGINT) is previous[signal.SIGINT]
    finally:
        for proc in spawned:
            if proc.returncode is None:
                real_terminate(proc)


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "killpg"),
    reason="spawn-interruption descendant cleanup requires POSIX process groups",
)
@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_capture_pi_command_signal_during_spawn_cleans_descendants_once(
    tmp_path, monkeypatch, signum
) -> None:
    from superharness.engine import pi_runtime

    fixture = _write_interrupt_pi_fixture(tmp_path, descendant=True)
    self_pid = tmp_path / "self.pid"
    descendant_pid = tmp_path / "descendant.pid"
    ready = tmp_path / "ready"
    monkeypatch.setenv("PI_CAPTURE_SELF", str(self_pid))
    monkeypatch.setenv("PI_CAPTURE_DESCENDANT", str(descendant_pid))
    monkeypatch.setenv("PI_CAPTURE_READY", str(ready))
    previous = {
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        signal.SIGINT: signal.getsignal(signal.SIGINT),
    }
    real_popen = pi_runtime.subprocess.Popen
    real_terminate = pi_runtime._terminate_process_tree
    spawned = []
    cleanup_calls = []
    installed_handlers = {}
    signal_calls = []

    def recording_signal(handled_signum, handler):
        signal_calls.append((handled_signum, handler))
        if handler is not previous[handled_signum]:
            installed_handlers[handled_signum] = handler
        return previous[handled_signum]

    def signal_before_assignment(*args, **kwargs):
        proc = real_popen(*args, **kwargs)
        spawned.append(proc)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if ready.exists():
                break
            if proc.poll() is not None:
                pytest.fail(
                    f"capture fixture exited before readiness: {proc.returncode}"
                )
            time.sleep(0.01)
        else:
            pytest.fail("capture fixture did not become ready")
        handler = installed_handlers.get(signum)
        if handler is None:
            pytest.fail(f"capture handler was not installed for signal {signum}")
        handler(signum, None)
        return proc

    def recording_terminate(proc):
        cleanup_calls.append(proc)
        real_terminate(proc)

    monkeypatch.setattr(pi_runtime.subprocess, "Popen", signal_before_assignment)
    monkeypatch.setattr(pi_runtime, "_terminate_process_tree", recording_terminate)
    monkeypatch.setattr(pi_runtime.signal, "signal", recording_signal)

    child_pids = []
    try:
        expected = KeyboardInterrupt if signum == signal.SIGINT else SystemExit
        with pytest.raises(expected) as exc_info:
            pi_runtime.capture_pi_command(
                [str(fixture)], cwd=str(tmp_path), timeout_seconds=5
            )

        if signum == signal.SIGTERM:
            assert exc_info.value.code == 128 + signal.SIGTERM
        assert len(cleanup_calls) == 1
        assert (signal.SIGTERM, previous[signal.SIGTERM]) in signal_calls
        assert (signal.SIGINT, previous[signal.SIGINT]) in signal_calls
        child_pids = [int(self_pid.read_text()), int(descendant_pid.read_text())]
        for child_pid in child_pids:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    os.kill(child_pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                pytest.fail(f"capture process survived signal cleanup: {child_pid}")
    finally:
        for proc in spawned:
            if proc.returncode is None:
                real_terminate(proc)
        for pid_path in (self_pid, descendant_pid):
            if not pid_path.exists():
                continue
            try:
                os.kill(int(pid_path.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("failure_kind", ["timeout", "os-error"])
def test_pi_runtime_exception_log_is_sanitized_and_falls_through(
    tmp_path, monkeypatch, caplog, failure_kind
) -> None:
    from superharness.engine import orchestrator
    from superharness.engine import pi_runtime

    raw_marker = "sensitive raw prompt marker"

    def fail_capture(argv, **kwargs):
        if failure_kind == "timeout":
            raise subprocess.TimeoutExpired(["pi", "-p", raw_marker], 1)
        raise OSError(raw_marker)

    fallback = _fixture_routing_payload(owner="codex-cli")
    monkeypatch.setattr(
        orchestrator,
        "_shuffle_chain",
        lambda: [
            ("pi", "shared/model", "Pi fixture"),
            ("codex", "fallback/model", "Codex fixture"),
        ],
    )
    monkeypatch.setattr(pi_runtime, "capture_pi_command", fail_capture)
    monkeypatch.setattr(
        orchestrator.subprocess,
        "run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(fallback),
            stderr="",
        ),
    )
    caplog.set_level("DEBUG", logger="superharness.engine.orchestrator")

    plan = orchestrator.Orchestrator(str(tmp_path)).route(
        {"id": "fixture", "title": raw_marker}
    )

    assert [subtask["owner"] for subtask in plan.subtasks] == ["codex-cli"]
    assert raw_marker not in caplog.text


def _write_oversize_pi_fixture(tmp_path: Path, mode: str) -> Path:
    fixture = tmp_path / f"pi-{mode}"
    if mode == "total":
        output_expression = "(b'sensitive-marker\\n' * 20)"
    elif mode == "record":
        output_expression = "(b'sensitive-marker' + b'x' * 100 + b'\\n')"
    else:
        output_expression = "b''"
    fixture.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time\n"
        f"os.write(sys.stdout.fileno(), {output_expression})\n"
        "sys.stdout.flush()\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    fixture.chmod(0o755)
    return fixture


@pytest.mark.parametrize("failure_kind", ["total", "record", "timeout"])
@_REQUIRES_POSIX_FIXTURE
def test_bounded_pi_capture_is_terminated_and_falls_through_without_raw_leak(
    tmp_path, monkeypatch, caplog, failure_kind
) -> None:
    from superharness.engine import orchestrator
    from superharness.engine import pi_runtime

    fixture = _write_oversize_pi_fixture(tmp_path, failure_kind)
    real_build = orchestrator._build_agent_argv
    real_capture = pi_runtime.capture_pi_command
    real_terminate = pi_runtime._terminate_process_tree
    terminated = []
    capture_errors = []

    def fake_build(binary, model, prompt):
        if binary == "pi":
            return [str(fixture)]
        return real_build(binary, model, prompt)

    def recording_terminate(proc):
        real_terminate(proc)
        terminated.append(proc)

    def recording_capture(*args, **kwargs):
        try:
            return real_capture(*args, **kwargs)
        except pi_runtime.PiCaptureError as exc:
            capture_errors.append(str(exc))
            raise

    fallback = _fixture_routing_payload(owner="codex-cli")
    monkeypatch.setattr(
        pi_runtime,
        "_MAX_CAPTURE_BYTES",
        64 if failure_kind == "total" else 256,
    )
    monkeypatch.setattr(pi_runtime, "_MAX_JSONL_RECORD_BYTES", 32)
    if failure_kind == "timeout":
        monkeypatch.setattr(orchestrator, "_ORCHESTRATOR_TIMEOUT", 0.05)
    monkeypatch.setattr(orchestrator, "_build_agent_argv", fake_build)
    monkeypatch.setattr(pi_runtime, "capture_pi_command", recording_capture)
    monkeypatch.setattr(pi_runtime, "_terminate_process_tree", recording_terminate)
    monkeypatch.setattr(
        orchestrator,
        "_shuffle_chain",
        lambda: [
            ("pi", "shared/model", "Pi fixture"),
            ("codex", "fallback/model", "Codex fixture"),
        ],
    )
    monkeypatch.setattr(
        orchestrator.subprocess,
        "run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=json.dumps(fallback),
            stderr="",
        ),
    )
    caplog.set_level("DEBUG", logger="superharness.engine.orchestrator")

    plan = orchestrator.Orchestrator(str(tmp_path)).route(
        {"id": "fixture", "title": "Bounded capture fixture"}
    )

    assert [subtask["owner"] for subtask in plan.subtasks] == ["codex-cli"]
    assert len(terminated) == 1
    assert terminated[0].returncode is not None
    expected_error = {
        "total": "total capture limit",
        "record": "record exceeded capture limit",
        "timeout": "capture timed out",
    }[failure_kind]
    assert capture_errors and expected_error in capture_errors[0]
    assert "sensitive-marker" not in caplog.text


@pytest.mark.parametrize(
    "binary", ["claude", "codex", "gemini", "opencode", "pi"]
)
def test_all_orchestrator_runtimes_receive_project_cwd(
    tmp_path, monkeypatch, binary
) -> None:
    from superharness.engine import orchestrator
    from superharness.engine import pi_runtime

    calls = []
    payload = _fixture_routing_payload(owner="codex-cli")

    def fake_candidate(argv, **kwargs):
        calls.append(kwargs)
        stdout = (
            _pi_orchestrator_stream(payload)
            if binary == "pi"
            else json.dumps(payload)
        )
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(
        orchestrator,
        "_shuffle_chain",
        lambda: [(binary, "fixture/model", "Fixture runtime")],
    )
    monkeypatch.setattr(orchestrator.subprocess, "run", fake_candidate)
    monkeypatch.setattr(pi_runtime, "capture_pi_command", fake_candidate)

    plan = orchestrator.Orchestrator(str(tmp_path)).route(
        {"id": "fixture", "title": "Cwd fixture"}
    )

    assert plan.decompose is True
    if binary == "pi":
        expected_calls = [
            {
                "cwd": str(tmp_path),
                "timeout_seconds": orchestrator._ORCHESTRATOR_TIMEOUT,
            }
        ]
    else:
        expected_calls = [
            {
                "cwd": str(tmp_path),
                "capture_output": True,
                "text": True,
                "timeout": orchestrator._ORCHESTRATOR_TIMEOUT,
                "check": False,
            }
        ]
    assert calls == expected_calls


def test_pi_orchestrator_evidence_record_is_complete() -> None:
    document = _MODEL_DOC.read_text()

    assert _orchestrator_evidence_record(document) is not None


def test_chain_pi_model_matches_manifest_max() -> None:
    from superharness.engine.orchestrator import _ORCHESTRATOR_CHAIN

    manifest = yaml.safe_load(_PI_MANIFEST.read_text())
    manifest_max = manifest["model_tiers"]["max"]["preferred"]
    pi_entries = [entry for entry in _ORCHESTRATOR_CHAIN if entry[0] == "pi"]

    assert len(pi_entries) == 1
    assert pi_entries[0][1] == manifest_max
