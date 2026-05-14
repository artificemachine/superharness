# YAML File Inventory — superharness

*Last updated: 2026-05-13 (post phase-4 cleanup + dead-code removal)*

---

## Keep — Operator-Authored Config (always YAML)

| File | Written by | Read by | Why YAML |
|------|-----------|---------|----------|
| `.superharness/profile.yaml` | `init_project.py`, `profile.py`, `workflow_cmd.py`, `onboard.py` | `profile.py`, `inbox_watch.py`, `lifecycle_rules.py`, `model_budget.py`, many commands | Human-edited project config: autonomy, primary_agent, budget, auto_close. |
| `.superharness/watcher.yaml` | `watcher_worker.py` | `status.py`, `watcher_worker.py` | Daemon configuration. Human-editable. |
| `.superharness/scheduled.yaml` | `schedule.py` | `schedule.py` | Cron-like schedule definitions. Operator-authored. |
| `.superharness/modules/{name}.yaml` | `registry.py`, `init_project.py` | `registry.py`, `loader.py` | Module capability manifests. Declarative spec. |
| `.superharness/skills/{name}.yaml` | `loader.py`, `skill_extractor.py` | `loader.py`, `skill_extractor.py` | Skill definitions. Config, not state. |
| `.superharness/hooks/*/HOOK.yaml` | Operator | `hooks.py` | Event binding definitions. Project-specific config. |
| `.superharness/adapter_manifests/{name}.yaml` | Bundled / operator | `smart_dispatch.py`, `session.py` | Agent capability manifests for smart dispatch. |

---

## Keep — Secrets (needs OS file permissions)

| File | Written by | Why YAML |
|------|-----------|----------|
| `.superharness/watcher-env.yaml` | `env_snapshot.py` (daemon startup) | Secrets snapshot (API keys, PATH). `chmod 600`. SQLite is world-readable — can't use it for secrets. |

---

## Keep — Agent Handoff Documents

| File | Written by | Why YAML |
|------|-----------|----------|
| `.superharness/handoffs/*.yaml` | `handoff_generate.py`, `handoff_write.py`, `state_writer.upsert_handoff` | Narrative agent documents (plans, reports, context). Git-tracked artifacts. SQLite holds a reference/index; the file is the readable artifact. |

---

## Keep — Export / Backup (SQLite snapshots)

Written only by `shux export-yaml`. **Never read back in production.** Safe to delete and regenerate at any time.

| File |
|------|
| `.superharness/export/contract.yaml` |
| `.superharness/export/inbox.yaml` |
| `.superharness/export/failures.yaml` |
| `.superharness/export/decisions.yaml` |
| `.superharness/export/handoffs/` |

---

## Debatable — Volatile Runtime Liveness

Short-lived files written by the watcher daemon. Could move to SQLite, no urgency.

| File | Notes |
|------|-------|
| `.superharness/agents/{id}.heartbeat.yaml` | Per-agent heartbeat. Atomic file write, no DB connection at write time. |
| `.superharness/agents/{runtime}.status.yaml` | Per-agent runtime status (active/idle/stopping/dead). Volatile. |
| `.superharness/watcher.heartbeat.yaml` | Watcher daemon liveness. Volatile. |

---

## Still Active — Not Yet Migrated to SQLite

These files are **still the primary source** for many production commands.
Removing them requires per-command refactoring (same pattern as the phase-1–4 work).

| File | Still written by | Still read by |
|------|-----------------|--------------|
| `.superharness/contract.yaml` | `task.py`, `verify.py`, `subtask_cancel.py`, `delegate.py`, `subtask_aggregator.py`, `onboard.py`, `discuss.py` | `task.py`, `delegate.py`, `verify.py`, `subtask_cancel.py`, `auto_dispatch.py`, `diff.py`, `contract_today.py`, `contract_validate.py`, `inbox_enqueue.py`, `dashboard-ui.py`, `cli.py`, `remember.py`, `onboard.py` |
| `.superharness/inbox.yaml` | `task.py`, `inbox_dispatch.py`, `inbox_enqueue.py`, `discuss.py`, `onboard.py` | `task.py`, `inbox_dispatch.py`, `inbox_enqueue.py`, `inbox_normalize.py`, `notify.py`, `recap.py`, `status.py`, `dashboard-ui.py` |

**Migration status:** SQLite is the source of truth for reads in `state_reader.get_tasks()`, `close_task`, `validate`, `adapter_payload`, `preflight`, `inbox_watch`. The commands listed above still read YAML directly — they haven't been migrated yet.

---

## Removed — Dead Code (completed 2026-05-13)

### Phase 1–4 cleanup (state layer)

| Removed | Was |
|---------|-----|
| `state_reader._inbox_from_yaml` | YAML inbox fallback |
| `state_reader._tasks_from_yaml` | YAML task fallback |
| `state_reader._contract_yaml` | YAML contract reader |
| `state_reader._handoffs_from_yaml` | YAML handoff reader |
| `state_reader.get_handoffs` yaml_only branch | YAML-first path |
| `close_task(contract_file, ...)` | Changed to `close_task(project_dir, ...)` — reads/writes SQLite |
| `preflight._check_prior_failures` YAML read | Replaced with `failures_dao.get_recent()` |
| `validate.py` contract.yaml path check | Replaced with `state.sqlite3` path check |
| `adapter_payload._load_failures/_decisions/_inbox` YAML fallback | Removed |
| `inbox_watch._ensure_task_in_sqlite` YAML seed | Removed |
| `inbox_watch` orphan reaper YAML fallback | Removed |
| `init_project` "Patch contract goal" block | Removed (contract.yaml never exists in new projects) |
| `init_project` directory listing | Updated to show `state.sqlite3` not dead YAML files |
| `context.py` dead `contract_path` variable | Removed |

### Dead-code sweep (2026-05-13)

| Removed | Was |
|---------|-----|
| `state_writer._export_contract_yaml` | Defined, never called anywhere |
| `state_writer._export_inbox_yaml` | Called only when `not is_sqlite_only()` — never true; removed function + call |
| `doctor.py` checks for `contract.yaml`, `decisions.yaml`, `failures.yaml` | Replaced with checks for `state.sqlite3` and `ledger.md` |
| `test_doctor.py` project fixture | Removed creation of `contract.yaml`, `decisions.yaml`, `failures.yaml`; replaced with SQLite init |

---

## Migration Reference

- **Test helper:** `tests/helpers.seed_sqlite_from_yaml(project_path)` — reads legacy YAML fixtures in tests and hydrates SQLite. Used only in test code; never called in production.
- **Import tool:** `shux import-yaml` (`yaml_io.py`) — one-time migration of YAML files to SQLite for projects upgrading from old installs.
- **`contract_io.py`:** `read_contract`/`write_contract` still used by `task.py`, `verify.py`, `subtask_cancel.py`, `delegate.py`, `onboard.py`, `discuss.py`, and `yaml_io.py` export/import. Not dead — still the primary I/O layer for unmigrated commands.
- **State backend:** `STATE_BACKEND=sqlite_only` (default). Override `dual` or `yaml_only` only for emergency rollback.

---

## What's Left to Migrate (future phases)

Priority order based on call frequency and risk:

| Command | What to change |
|---------|---------------|
| `verify.py` | `verify(contract_file, ...)` → read `verified` from SQLite, write back via `tasks_dao.update` |
| `subtask_cancel.py` | Cancel subtask status via `set_task_status`, not contract.yaml write |
| `task.py` | Largest file (~1000 lines); all status transitions, archive, delete — migrate to `tasks_dao` |
| `delegate.py` | Task field reads (`_get_task_field`, etc.) → replace with `tasks_dao.get(conn, task_id).field` |
| `onboard.py` | Remove contract.yaml + inbox.yaml creation; use `shux task create` and `shux delegate` |
| `inbox_enqueue.py` | Already has SQLite seed path; complete the migration |
| `dashboard-ui.py` | `contract_tasks()` already tries SQLite first; remove YAML fallback |
| `discuss.py`, `auto_dispatch.py`, `diff.py`, `contract_today.py` | Lower priority; replace reads with `state_reader.get_tasks()` |
