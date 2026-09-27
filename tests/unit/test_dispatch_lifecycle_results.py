"""F-05/F-06 (iteration 3): every non-terminal reconcile decision writes a result.

Defect: `_reconcile_state()` could leave an inbox item with NO `result` and NO
`failed_reason` recorded — the failures journal then shows an empty cause, and
skipped/paused items carry no machine-readable decision trace.

Contract under test (format matches the existing skip write site in
`_skip_already_done_discussion_round`: `failed_reason = "skipped: <reason>"`):
  * skip/waiting decisions        -> result == "skipped", failed_reason "skipped: <reason>"
  * launch-failure decisions      -> result == "blocked",  failed_reason non-empty
  * every such decision re-stamps the item's heartbeat timestamp.

All fixtures are hermetic: inbox lives in tmp_path, every inbox write is a
local YAML mutation (no `python -m superharness.engine.inbox` subprocess),
git/liveness/SQLite/notify/benchmark probes are mocked, and `subprocess.run`
inside the module is trapped to fail loudly if anything tries to spawn.
"""

import time
from contextlib import ExitStack
from unittest.mock import patch

import yaml

from superharness.commands.inbox_dispatch import DispatchContext, _reconcile_state

ITEM_ID = "inbox-item-lifecycle-1"
AGENT = "worker-agent"
TASK = "task-lifecycle-1"
INITIAL_TS = "2026-01-01T00:00:00Z"


def _make_inbox(tmp_path, *, status="launched", extra=None):
    """Write a one-item inbox YAML in tmp_path (never a real operator state)."""
    item = {
        "id": ITEM_ID,
        "to": AGENT,
        "task": TASK,
        "status": status,
        "created_at": INITIAL_TS,
        "launched_at": INITIAL_TS,
        "last_heartbeat": INITIAL_TS,
    }
    if extra:
        item.update(extra)
    inbox_file = tmp_path / "inbox.yaml"
    inbox_file.write_text(yaml.dump([item], sort_keys=True))
    return str(inbox_file)


def _make_ctx(tmp_path, *, item_extra=None):
    inbox_file = _make_inbox(tmp_path, extra=item_extra)
    item = {
        "id": ITEM_ID,
        "to": AGENT,
        "task": TASK,
        "status": "launched",
    }
    item.update(item_extra or {})
    return DispatchContext(
        project_dir=str(tmp_path / "project"),
        inbox_file=inbox_file,
        contract_file=str(tmp_path / "contract.yaml"),
        print_only=False,
        non_interactive=True,
        codex_bypass=False,
        launcher_timeout=0,
        script_dir=str(tmp_path),
        sqlite_primary=False,
        item_id=ITEM_ID,
        item_to=AGENT,
        item_task=TASK,
        exec_project=str(tmp_path),
        task_log="",
        launch_start=time.time(),
        item=item,
    )


def _load_item(ctx):
    items = yaml.safe_load(open(ctx.inbox_file).read())
    return next(i for i in items if i["id"] == ITEM_ID)


def _run_reconcile(
    ctx,
    tmp_path,
    *,
    task_row=None,
    dirty=False,
    pid_alive_result=True,
):
    """Run _reconcile_state with all side-effects redirected into tmp_path/mocks.

    - `_set_inbox_status` / `_set_inbox_field` mutate the tmp inbox YAML directly
      (the production path spawns `python -m superharness.engine.inbox`).
    - `state_reader.get_task` is pinned to `task_row` (None = no task file).
    - git dirty probe, pid liveness probe, SQLite mirrors, notify, benchmark
      and any subprocess spawn are mocked/trapped.
    """

    def fake_set_status(inbox_file, item_id, from_, to, now, stamp_key):
        items = yaml.safe_load(open(inbox_file).read())
        hit = False
        for it in items:
            if it["id"] == item_id and it.get("status") == from_:
                it["status"] = to
                it[stamp_key] = now
                hit = True
        if hit:
            with open(inbox_file, "w") as fh:
                yaml.dump(items, fh, sort_keys=True)
        return hit

    def fake_set_field(inbox_file, item_id, key, value):
        items = yaml.safe_load(open(inbox_file).read())
        for it in items:
            if it["id"] == item_id:
                it[key] = value
        with open(inbox_file, "w") as fh:
            yaml.dump(items, fh, sort_keys=True)

    def no_subprocess(*args, **kwargs):
        raise AssertionError(
            f"_reconcile_state must not spawn subprocesses in tests: {args!r}"
        )

    with ExitStack() as stack:
        mock_lock = stack.enter_context(
            patch("superharness.commands.inbox_dispatch._MkdirLock")
        )
        mock_lock.return_value.acquire_with_retry = lambda *a: True
        mock_lock.return_value.release = lambda: None

        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._set_inbox_status",
                side_effect=fake_set_status,
            )
        )
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._set_inbox_field",
                side_effect=fake_set_field,
            )
        )
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._has_dirty_worktree",
                return_value=dirty,
            )
        )
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch.pid_alive",
                return_value=pid_alive_result,
            )
        )
        stack.enter_context(
            patch(
                "superharness.engine.state_reader.get_task",
                return_value=task_row,
            )
        )
        for target in (
            "superharness.commands.inbox_dispatch._sqlite_mirror_dispatch",
            "superharness.commands.inbox_dispatch._sqlite_record_review",
            "superharness.commands.notify_desktop.notify_task_event",
            "superharness.engine.benchmark.record_dispatch",
        ):
            stack.enter_context(patch(target))
        # Hard guarantee: nothing in the reconcile path may spawn anything.
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch.subprocess.run",
                side_effect=no_subprocess,
            )
        )
        return _reconcile_state(ctx)


def test_reconcile_writes_result_on_skip(tmp_path):
    """Waiting condition (pending_user_approval → paused) must record
    result=skipped with a failed_reason in the `skipped: <reason>` format."""
    ctx = _make_ctx(tmp_path)
    _run_reconcile(ctx, tmp_path, task_row={"status": "pending_user_approval"})

    item = _load_item(ctx)
    assert item["status"] == "paused"
    assert item.get("result") == "skipped", (
        f"non-terminal skip decision must write result=skipped, got {item.get('result')!r}"
    )
    assert item.get("failed_reason") == "skipped: awaiting_user_approval", (
        f"failed_reason must follow 'skipped: <reason>' format, got {item.get('failed_reason')!r}"
    )


def test_reconcile_blocked_writes_failed_reason(tmp_path):
    """A reconciled launch failure (task final state `failed`) must record
    result=blocked and a NON-EMPTY failed_reason (F-05: no empty causes)."""
    ctx = _make_ctx(tmp_path)
    _run_reconcile(ctx, tmp_path, task_row={"status": "failed"})

    item = _load_item(ctx)
    assert item["status"] == "failed"
    assert item.get("result") == "blocked", (
        f"launch-failure decision must write result=blocked, got {item.get('result')!r}"
    )
    reason = item.get("failed_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"failed_reason must be non-empty on a blocked reconcile, got {reason!r}"
    )
    assert not reason.startswith("skipped:"), (
        "a launch failure is blocked, not skipped"
    )


def test_reconcile_no_task_file_writes_skipped(tmp_path):
    """No task row for the claimed task (task file missing) is a skip decision:
    result=skipped, failed_reason `skipped: ...` — never an unlabelled item."""
    ctx = _make_ctx(tmp_path)
    _run_reconcile(ctx, tmp_path, task_row=None, dirty=False)

    item = _load_item(ctx)
    assert item.get("result") == "skipped", (
        f"no-task-file path must write result=skipped, got {item.get('result')!r}"
    )
    reason = item.get("failed_reason") or ""
    assert reason.startswith("skipped:"), (
        f"failed_reason must follow 'skipped: <reason>' format, got {reason!r}"
    )
    assert "task" in reason.lower()


def test_reconcile_agent_dead_writes_skipped(tmp_path):
    """Same missing-task-row route, but the launched agent process is dead
    (module liveness probe `pid_alive` mocked False): still a skip decision,
    with the dead agent named in the reason."""
    ctx = _make_ctx(tmp_path, item_extra={"pid": 4242})
    _run_reconcile(
        ctx, tmp_path, task_row=None, dirty=False, pid_alive_result=False
    )

    item = _load_item(ctx)
    assert item.get("result") == "skipped", (
        f"dead-agent path must write result=skipped, got {item.get('result')!r}"
    )
    reason = item.get("failed_reason") or ""
    assert reason.startswith("skipped:"), (
        f"failed_reason must follow 'skipped: <reason>' format, got {reason!r}"
    )
    assert "dead" in reason.lower()


def test_reconcile_heartbeat_updated_on_decision(tmp_path):
    """Every reconcile decision re-stamps the item's heartbeat timestamp so
    stale-heartbeat recovery does not double-count an already-decided item."""
    ctx = _make_ctx(tmp_path)
    _run_reconcile(ctx, tmp_path, task_row={"status": "in_progress"}, dirty=False)

    item = _load_item(ctx)
    heartbeat = item.get("last_heartbeat")
    assert heartbeat is not None, "heartbeat timestamp must be written on a decision"
    assert heartbeat != INITIAL_TS, (
        "heartbeat must MOVE on a reconcile decision, "
        f"still at launch stamp {INITIAL_TS!r}"
    )


# ---------------------------------------------------------------------------
# Iteration 4 (F-05/F-06 slice 2): in-flight result at launch.
#
# Defect: at launch the dispatcher never marks the local task `in_progress`
# and never writes a result trace on the inbox item while the agent runs —
# no `result`, no `dispatch_started_at`, no heartbeat, so a crash mid-run is
# invisible to stale-heartbeat recovery.
#
# The module has no function named `inbox_dispatch_start`; the real launch
# point is `_execute_agent` (invoked by `_do_dispatch` step 6 right after
# `_transition_to_launched`).  The tests drive it directly with its launch
# seams mocked at the module boundary (`_run_with_timeout`, `_inbox_cmd`,
# `subprocess.run` trapped) and the local task held in a dict-backed fake
# store validated against the REAL legal-transition graph — no SQLite, no
# subprocess, tmp_path only.
#
# Canonical in-flight result value: `result == "in_progress"` — same word as
# the task status the launch transition produces, and consistent with the
# value `_reconcile_state` tests already use for a running task
# (task_row={"status": "in_progress"}); decision outcomes (`skipped`,
# `blocked`) overwrite it only after the run ends.
# ---------------------------------------------------------------------------

import re as _re

from superharness.commands.inbox_dispatch import _execute_agent
from superharness.engine.next_action import validate_status_transition

TS_SHAPE = _re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _fake_task_store(initial_status):
    """Dict-backed local task store validated against the real state machine.

    Mirrors `state_writer.set_task_status` semantics that matter here:
    same-status write is an idempotent no-op success; an illegal transition
    is refused (returns False, state untouched); legal moves flip the state.
    """
    return {"status": initial_status, "flips": 0}


def _run_start(ctx, *, task_store):
    """Drive the real launch point `_execute_agent` with every side effect
    redirected into tmp_path / mocks (same seams and fakes as `_run_reconcile`).
    """

    def fake_set_field(inbox_file, item_id, key, value):
        items = yaml.safe_load(open(inbox_file).read())
        for it in items:
            if it["id"] == item_id:
                it[key] = value
        with open(inbox_file, "w") as fh:
            yaml.dump(items, fh, sort_keys=True)

    def no_subprocess(*args, **kwargs):
        raise AssertionError(
            f"launch path must not spawn subprocesses in tests: {args!r}"
        )

    # Reach the real launch call with the timeout runner (no Popen path).
    ctx.effective_timeout = 30
    ctx.wrapped_args = ["true"]
    ctx.spawn_env = {}

    def get_task(project_dir, task_id):
        return {"id": task_id, "status": task_store["status"]}

    def set_task_status(project_dir, task_id, status, *, from_status=None, force=False, **fields):
        current = task_store["status"]
        if current == status:
            return True
        try:
            validate_status_transition(current, status)
        except ValueError:
            return False
        task_store["status"] = status
        task_store["flips"] += 1
        return True

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._set_inbox_field",
                side_effect=fake_set_field,
            )
        )
        # pid clear/set writes go through _inbox_cmd directly — neutralise.
        stack.enter_context(
            patch("superharness.commands.inbox_dispatch._inbox_cmd")
        )
        # The spawn itself: patched at the module boundary, returns success.
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._run_with_timeout",
                return_value=0,
            )
        )
        stack.enter_context(
            patch("superharness.engine.state_reader.get_task", side_effect=get_task)
        )
        stack.enter_context(
            patch(
                "superharness.engine.state_writer.set_task_status",
                side_effect=set_task_status,
            )
        )
        # Hard guarantee: nothing in the launch path may spawn anything.
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch.subprocess.run",
                side_effect=no_subprocess,
            )
        )
        _execute_agent(ctx)


def test_start_writes_in_progress_result(tmp_path):
    """Launching an approved task must leave a complete in-flight trace:
    local task `in_progress`, item result `in_progress`, dispatch_started_at
    written, heartbeat refreshed — all before/at the spawn, not after."""
    ctx = _make_ctx(tmp_path)
    task_store = _fake_task_store("plan_approved")
    _run_start(ctx, task_store=task_store)

    assert task_store["status"] == "in_progress", (
        "launch must transition the local task plan_approved -> in_progress, "
        f"got {task_store['status']!r}"
    )
    item = _load_item(ctx)
    assert item.get("result") == "in_progress", (
        "in-flight item must carry the canonical in-flight result "
        f"'in_progress', got {item.get('result')!r}"
    )
    started = item.get("dispatch_started_at")
    assert isinstance(started, str) and TS_SHAPE.match(started), (
        f"dispatch_started_at must be a UTC Z stamp, got {started!r}"
    )
    heartbeat = item.get("last_heartbeat")
    assert isinstance(heartbeat, str) and TS_SHAPE.match(heartbeat), (
        f"launch must stamp last_heartbeat, got {heartbeat!r}"
    )
    assert heartbeat != INITIAL_TS, "launch heartbeat must move off the stale stamp"


def test_start_in_progress_idempotent(tmp_path):
    """Running the same start flow twice (watcher restart / re-entry) must not
    duplicate the task transition nor clobber the first dispatch_started_at:
    one flip, one start stamp (first value wins), fields stay coherent."""
    ctx = _make_ctx(tmp_path)
    task_store = _fake_task_store("plan_approved")

    _run_start(ctx, task_store=task_store)
    first = _load_item(ctx)
    first_started = first.get("dispatch_started_at")
    assert first_started and TS_SHAPE.match(first_started)

    _run_start(ctx, task_store=task_store)  # second start, same run

    assert task_store["status"] == "in_progress"
    assert task_store["flips"] == 1, (
        "second launch must be an idempotent no-op on task state, "
        f"got {task_store['flips']} state flips"
    )
    item = _load_item(ctx)
    assert item.get("result") == "in_progress"
    assert item.get("dispatch_started_at") == first_started, (
        "dispatch_started_at must keep the FIRST value, not be overwritten"
    )
    heartbeat = item.get("last_heartbeat")
    assert isinstance(heartbeat, str) and TS_SHAPE.match(heartbeat)


# ---------------------------------------------------------------------------
# Iteration 5 (F-05/F-06 slice 3): reconcile maps a `report_ready` task to
# inbox status `waiting_review` — never to failed/blocked.
#
# Defect: `_reconcile_state` has no branch for the task state `report_ready`
# (engine/lifecycle_rules.py:88-99 `report_ready`/`report_ready_at`; the
# dashboard puts it in the review queue, engine/dashboard_presenter.py:137,167;
# engine/next_action.py:90-93 lists its only successors as review verdicts).
# A finished-work-awaiting-review task therefore fell into the iteration-3
# `else` classification and was recorded as a BLOCKED dispatch failure.
#
# Canonical decision (documented in inbox_dispatch.py):
#   * task `report_ready` -> inbox item status `waiting_review`
#   * canonical waiting result value: `result == "waiting_review"` — same
#     word as the inbox status, mirroring the in-flight convention where the
#     result equals the state the transition produced ("in_progress"); the
#     decision outcomes (`skipped`/`blocked`) stay reserved for failures and
#     waits-with-no-work, which this is not.
#   * `failed_reason` stays non-empty (iteration-3 contract: every decision
#     carries a reason) but must NOT be a failure reason: it names the wait
#     (`waiting_review: ...`), never "dispatch failed" nor "skipped:".
#
# Hermetic: same `_run_reconcile` seams as the tests above (tmp inbox YAML,
# pinned task row, mocked status/field writers, probes, SQLite, notify,
# subprocess.run trapped).
# ---------------------------------------------------------------------------


def test_reconcile_report_ready_sets_waiting_review(tmp_path):
    """A task whose state says the report is ready for human review must land
    the inbox item in `waiting_review` with a waiting result — not failed,
    not paused, and never classified as a blocked dispatch failure."""
    ctx = _make_ctx(tmp_path)
    _run_reconcile(ctx, tmp_path, task_row={"status": "report_ready"})

    item = _load_item(ctx)
    assert item["status"] == "waiting_review", (
        "a report_ready task must transition the inbox item to "
        f"status 'waiting_review', got {item['status']!r}"
    )
    assert item["status"] not in ("failed", "paused"), (
        "waiting-for-review is not a failure nor a pause"
    )
    assert item.get("result") == "waiting_review", (
        "the canonical waiting result value is 'waiting_review' (same word "
        f"as the status), got {item.get('result')!r}"
    )
    reason = item.get("failed_reason") or ""
    assert reason, (
        "iteration-3 contract: every reconcile decision records a reason"
    )
    assert "dispatch failed" not in reason.lower(), (
        "a report awaiting review must NOT be recorded as a dispatch "
        f"failure, got {reason!r}"
    )
    assert not reason.startswith("skipped:"), (
        f"waiting for review is not a skip, got {reason!r}"
    )
    assert reason.lower().startswith("waiting_review"), (
        "the reason must name the wait, e.g. 'waiting_review: <detail>', "
        f"got {reason!r}"
    )
    heartbeat = item.get("last_heartbeat")
    assert isinstance(heartbeat, str) and TS_SHAPE.match(heartbeat), (
        f"the waiting_review decision must re-stamp last_heartbeat, got {heartbeat!r}"
    )
    assert heartbeat != INITIAL_TS, (
        "heartbeat must MOVE on the waiting_review decision"
    )


# ---------------------------------------------------------------------------
# Iteration 6 (R4): terminal paths must stop lying about in_progress.
#
# `_mark_item_in_progress_at_launch` stamps result="in_progress" at launch,
# but the two TERMINAL exits — the reconcile `done` branch and `_handle_failure`
# — never overwrote it. A completed item was indistinguishable from a crashed
# one: same stale "in_progress" forever. Iteration-3 tests only pinned
# skipped/blocked and in-flight stamps; nothing pinned these two paths.
# ---------------------------------------------------------------------------


def test_done_path_clears_in_progress_result(tmp_path):
    """Reconcile `done` must record result="done" — never keep in_progress."""
    ctx = _make_ctx(tmp_path, item_extra={"result": "in_progress"})
    _run_reconcile(ctx, tmp_path, task_row={"status": "done"})

    item = _load_item(ctx)
    assert item["status"] == "done"
    assert item.get("result") == "done", (
        "done is terminal: a stale result='in_progress' makes a completed "
        f"item indistinguishable from a crashed one, got {item.get('result')!r}"
    )
    assert item.get("last_heartbeat", INITIAL_TS) != INITIAL_TS, (
        "the terminal done decision must refresh last_heartbeat like every "
        "other recorded decision"
    )


def test_handle_failure_writes_failed_result(tmp_path):
    """_handle_failure must record result='failed' + non-empty failed_reason."""
    from superharness.commands.inbox_dispatch import _handle_failure

    # The rc=1 launcher seam, exactly as the failure path consumes it.
    ctx = _make_ctx(tmp_path, item_extra={"result": "in_progress"})
    ctx.launcher_rc = 1

    class _Cls:
        category = "crash"
        explain = "launcher exited rc=1"
        retryable = False

    def fake_set_status(inbox_file, item_id, from_, to, now, stamp_key):
        items = yaml.safe_load(open(inbox_file).read())
        hit = False
        for it in items:
            if it["id"] == item_id and it.get("status") == from_:
                it["status"] = to
                it[stamp_key] = now
                hit = True
        if hit:
            with open(inbox_file, "w") as fh:
                yaml.dump(items, fh, sort_keys=True)
        return hit

    def fake_set_field(inbox_file, item_id, key, value):
        items = yaml.safe_load(open(inbox_file).read())
        for it in items:
            if it["id"] == item_id:
                it[key] = value
        with open(inbox_file, "w") as fh:
            yaml.dump(items, fh, sort_keys=True)

    with ExitStack() as stack:
        mock_lock = stack.enter_context(
            patch("superharness.commands.inbox_dispatch._MkdirLock")
        )
        mock_lock.return_value.acquire_with_retry = lambda *a: True
        mock_lock.return_value.release = lambda: None
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._set_inbox_status",
                side_effect=fake_set_status,
            )
        )
        stack.enter_context(
            patch(
                "superharness.commands.inbox_dispatch._set_inbox_field",
                side_effect=fake_set_field,
            )
        )
        for target in (
            "superharness.commands.inbox_dispatch._inbox_cmd",
            "superharness.commands.inbox_dispatch._sqlite_mirror_dispatch",
            "superharness.commands.inbox_dispatch._sqlite_record_review",
            "superharness.commands.inbox_dispatch.subprocess.run",
            "superharness.engine.ledger_dao.decision_log",
            "superharness.commands.notify_desktop.notify_task_event",
            "superharness.engine.failure_patterns.record_failure",
            "superharness.engine.benchmark.record_dispatch",
            "superharness.engine.failure_classifier.classify",
            "superharness.engine.db.get_connection",
        ):
            stack.enter_context(patch(target))
        stack.enter_context(
            patch(
                "superharness.engine.failure_classifier.classify",
                return_value=_Cls(),
            )
        )

        rc = _handle_failure(ctx)

    assert rc == 1
    item = _load_item(ctx)
    assert item["status"] == "failed"
    assert item.get("result") == "failed", (
        "a failed dispatch must overwrite the in-flight result, got "
        f"{item.get('result')!r}"
    )
    reason = item.get("failed_reason")
    assert isinstance(reason, str) and reason.strip(), (
        f"failed_reason must be non-empty on the failure path, got {reason!r}"
    )
