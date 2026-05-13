# Plan: Wizard + Gateway Adaptation — Iteration Map (TDD + E2E)

Source: `notes/1_ai/wizard_and_demo/setup-wizard-pattern.md` (vault)
Status: proposal — not yet tasked

---

## Overview

Each iteration follows RED → GREEN → REFACTOR and closes with an E2E test that
proves the vertical slice works end-to-end before the next iteration builds on it.

Dependency order:
```
I1 (primitives) → I2 (registry + shell) → I3 (sections) → I4 (quick-setup + summary)
I5 (operator_commands table) → I6 (gateway listener) → I7 (gateway wizard + CLI)
I4 + I7 → I8 (full integration)
```

---

## Iteration 1 — Prompt primitives

**Files:** `src/superharness/ui/__init__.py`, `src/superharness/ui/prompts.py`,
`tests/unit/test_ui_prompts.py`

### RED
- `test_prompt_returns_default_on_empty_input`
- `test_prompt_yes_no_default_true`
- `test_prompt_yes_no_default_false`
- `test_prompt_choice_returns_index`
- `test_prompt_choice_numbered_fallback_when_curses_unavailable`
- `test_prompt_choice_enter_returns_default_index`
- `test_prompt_checklist_cancel_returns_preselected`
- `test_is_interactive_stdin_false_in_subprocess`

### GREEN
`ui/prompts.py`: `prompt`, `prompt_choice` (curses + numbered fallback),
`prompt_yes_no`, `prompt_checklist`, `is_interactive_stdin`, five print helpers.
Copy Hermes primitives verbatim; replace `Colors` with local ANSI constants.

### REFACTOR
- Extract curses teardown into a context manager so test isolation is clean
- Ensure all prompts catch `KeyboardInterrupt` / `EOFError` consistently

### E2E
```bash
echo "" | python -m superharness.ui.prompts --smoke
# exits 0, prints "prompts ok"
```

---

## Iteration 2 — Section registry + onboard shell

**Files:** `src/superharness/commands/onboard.py` (rewrite structure only — sections
are stubs), `tests/unit/test_onboard_shell.py`

### RED
- `test_onboard_section_only_mode_runs_single_section` (`shux onboard agent`)
- `test_onboard_unknown_section_prints_error`
- `test_onboard_non_interactive_prints_copy_paste_guidance`
- `test_onboard_returning_user_shows_menu` (`.superharness/state.sqlite3` present)
- `test_onboard_first_time_runs_all_sections_in_order`
- `test_onboard_state_saved_between_sections` (crash mid-run → resume picks up)

### GREEN
- `ONBOARD_SECTIONS` registry
- `run_onboard_wizard(args)` orchestrator with: headless gate, section-only path,
  returning-user detection + `prompt_choice` menu, first-time linear path
- Each section is a stub: `print_header(label); pass`
- State file: `profile.yaml: _config_version` integer (replaces `onboarding.yaml`)

### REFACTOR
- Remove `_STEPS` list and `onboarding.yaml` tracking from current `onboard.py`
- Remove duplicated init logic between `onboard.py` and `init_project.py`

### E2E
```bash
tmp=$(mktemp -d)
shux onboard --project "$tmp" --non-interactive
# exits 0, prints non-interactive guidance block, no prompts hang
```

---

## Iteration 3 — Section implementations

**Files:** `src/superharness/commands/onboard.py` (fill in stubs),
`src/superharness/commands/init_project.py` (refactor prompts to use `ui.prompts`),
`tests/unit/test_onboard_sections.py`

### RED — one test class per section

**project section**
- `test_setup_project_auto_detects_python_stack`
- `test_setup_project_enter_keeps_detected_value`
- `test_setup_project_writes_to_profile_yaml`

**agent section**
- `test_setup_agent_writes_autonomy_to_profile`
- `test_setup_agent_round_skip_flag_default_true`
- `test_setup_agent_skip_on_enter_keeps_current`

**git section**
- `test_setup_git_solo_adds_superharness_to_root_gitignore`
- `test_setup_git_team_does_not_add_to_root_gitignore`
- `test_setup_git_always_writes_inner_gitignore`

**hooks section**
- `test_setup_hooks_calls_install_hooks`
- `test_setup_hooks_detects_stale_worktree_path_in_settings_json`
- `test_setup_hooks_offers_to_fix_stale_path`

**watcher section**
- `test_setup_watcher_macos_offers_launchd`
- `test_setup_watcher_linux_offers_systemd`
- `test_setup_watcher_prints_manual_command_on_other_os`

### GREEN
Implement each `_setup_<section>(config)` function using primitives from I1.
All read current value from `profile.yaml`, show it, prompt, mutate, save.

### REFACTOR
- Extract `_read_profile` / `_write_profile` helpers used by all sections
- `init_project.py` interactive path delegates to the same section functions

### E2E
```bash
tmp=$(mktemp -d) && git init "$tmp" --quiet
echo "" | shux onboard --project "$tmp" --section agent
# profile.yaml exists with autonomy field; exit 0
```

---

## Iteration 4 — Quick-setup + summary printer

**Files:** `src/superharness/commands/onboard.py` (add `_run_quick_setup` +
`_print_setup_summary`), `tests/unit/test_onboard_quick.py`

### RED
- `test_quick_setup_skips_when_everything_configured`
- `test_quick_setup_prompts_only_unconfigured_fields`
- `test_quick_setup_bumps_config_version_after_new_field_added`
- `test_quick_setup_new_version_field_prompts_existing_users`
- `test_summary_printer_shows_all_configured_sections`
- `test_summary_printer_shows_missing_sections_with_configure_hint`

### GREEN
- `_get_missing_profile_fields()` — compares `profile.yaml` against `DEFAULT_PROFILE`
  keyed by `_config_version`
- `_run_quick_setup(config)` — prompts only gaps; bumps version; calls summary
- `_print_setup_summary(config)` — one-line status per section under `◆` headers

### REFACTOR
- `DEFAULT_PROFILE` dict with `_config_version: 1` as the canonical schema
- `PROFILE_FIELDS_BY_VERSION = {2: ["gateway.events"], 3: [...]}` for future fields

### E2E
```bash
tmp=$(mktemp -d) && git init "$tmp" --quiet
# First run: full setup
echo -e "\n\n\n\n\n\n" | shux onboard --project "$tmp" --non-interactive
# Second run: quick setup should print "Everything is configured"
echo "" | shux onboard --project "$tmp" --quick 2>&1 | grep "Everything"
```

---

## Iteration 5 — operator_commands table + DAO

**Files:** `src/superharness/engine/db.py` (extend `init_db`),
`src/superharness/engine/operator_commands_dao.py` (new),
`tests/unit/test_operator_commands_dao.py`

### RED
- `test_init_db_creates_operator_commands_table`
- `test_enqueue_writes_row_with_pending_status`
- `test_enqueue_deduplicates_by_idempotency_key`
- `test_get_pending_returns_only_unprocessed_rows`
- `test_mark_processed_sets_processed_at_and_result`
- `test_mark_processed_is_idempotent`

### GREEN
`operator_commands` table schema:
```sql
CREATE TABLE IF NOT EXISTS operator_commands (
    id              TEXT PRIMARY KEY,
    source          TEXT NOT NULL,          -- telegram | openclaw | cli
    sender_id       TEXT,                   -- platform user id
    idempotency_key TEXT UNIQUE,            -- telegram message_id or cli uuid
    raw_text        TEXT,
    parsed_command  TEXT,                   -- approve | reject | close | reset | ...
    task_id         TEXT,
    args            TEXT,                   -- JSON blob for extra args
    status          TEXT DEFAULT 'pending', -- pending | processed | rejected | error
    result          TEXT,
    created_at      TEXT NOT NULL,
    processed_at    TEXT
)
```

`operator_commands_dao.py`: `enqueue`, `get_pending`, `mark_processed`, `mark_rejected`.

### REFACTOR
- Consistent row factory (`.row_factory = sqlite3.Row`) matching `tasks_dao` pattern
- `mark_processed` / `mark_rejected` are idempotent no-ops if already processed

### E2E
```bash
python -c "
from superharness.engine.db import get_connection, init_db
from superharness.engine import operator_commands_dao as dao
import tempfile, os
tmp = tempfile.mkdtemp()
conn = get_connection(tmp); init_db(conn)
dao.enqueue(conn, id='x1', source='cli', idempotency_key='ik1',
            parsed_command='approve', task_id='t-abc', created_at='2026-01-01T00:00:00Z')
conn.commit()
rows = dao.get_pending(conn)
assert len(rows) == 1
print('operator_commands dao ok')
"
```

---

## Iteration 6 — Gateway listener process

**Files:** `src/superharness/commands/gateway_listener.py` (new),
`tests/unit/test_gateway_listener.py`

### RED
- `test_unknown_sender_is_rejected_no_row_written`
- `test_known_sender_approve_command_writes_row`
- `test_telegram_message_id_deduplicates_redelivered_message`
- `test_malformed_command_sends_help_reply_no_row`
- `test_listener_exits_gracefully_on_api_error_with_backoff`
- `test_parse_command_approve` / `reject` / `close` / `reset`

### GREEN
`gateway_listener.py`:
- `parse_command(text) -> (command, task_id, args) | None`
- `is_allowed_sender(sender_id, allowlist) -> bool`
- `handle_message(msg, conn, allowlist)` — validates, deduplicates, writes row
- `run_telegram_listener(project_dir, token, allowlist)` — polling loop with
  exponential backoff; calls `handle_message` per update; stateless (all state in SQLite)

Mocked Telegram API in tests via `unittest.mock.patch`.

### REFACTOR
- `parse_command` returns a typed dataclass, not a tuple
- Backoff logic extracted to a shared `_backoff_retry` utility

### E2E
```bash
# Inject a mock message directly into the handler (no real Telegram needed)
python -c "
import tempfile
from superharness.engine.db import get_connection, init_db
from superharness.commands.gateway_listener import handle_message
tmp = tempfile.mkdtemp()
conn = get_connection(tmp); init_db(conn)
msg = {'message_id': 42, 'from': {'id': '99999'}, 'text': 'approve t-abc123'}
handle_message(msg, conn, allowlist=['99999'])
conn.commit()
from superharness.engine import operator_commands_dao as dao
rows = dao.get_pending(conn)
assert rows[0]['task_id'] == 't-abc123'
print('gateway listener e2e ok')
"
```

---

## Iteration 7 — Gateway wizard section + CLI commands

**Files:** `src/superharness/commands/onboard.py` (add `_setup_gateway`),
`src/superharness/commands/approve.py` (new),
`tests/unit/test_onboard_gateway_section.py`,
`tests/unit/test_approve_cmd.py`

### RED

**Gateway wizard section**
- `test_setup_gateway_telegram_saves_token_and_allowlist`
- `test_setup_gateway_skips_if_already_configured_and_no_reconfigure`
- `test_setup_gateway_event_checklist_saves_to_profile`
- `test_setup_gateway_openclaw_saves_relay_url`

**CLI commands**
- `test_approve_cmd_writes_operator_command_row`
- `test_reject_cmd_writes_row_with_reason`
- `test_approve_cmd_missing_state_sqlite_exits_1`
- `test_approve_cmd_idempotent_on_duplicate_call`

### GREEN
- `_setup_gateway(config)`: Hermes gateway pattern for Telegram + OpenClaw;
  event checklist saved to `profile.yaml: gateway.events`
- `approve.py`: `shux approve <task-id>` and `shux reject <task-id> <reason>` write
  directly to `operator_commands` table via `operator_commands_dao.enqueue`

### REFACTOR
- Gateway env var saving unified with `_save_env_value` from I3
- `approve.py` and `reject.py` share a `_write_operator_command` helper

### E2E
```bash
tmp=$(mktemp -d) && git init "$tmp" --quiet
shux init --project "$tmp" Demo Python active
shux task create --project "$tmp" --title "Test task" --id t-e2e01
shux approve --project "$tmp" t-e2e01
# operator_commands table has 1 pending approve row
python -c "
from superharness.engine.db import get_connection
from superharness.engine import operator_commands_dao as dao
conn = get_connection('$tmp')
rows = dao.get_pending(conn)
assert any(r['task_id'] == 't-e2e01' for r in rows)
print('approve cli e2e ok')
"
```

---

## Iteration 8 — Full integration

**Files:** `tests/integration/test_wizard_gateway_integration.py` (new)

### RED
- `test_full_onboard_then_approve_via_cli_then_watcher_transitions_task`
- `test_onboard_quick_after_gateway_configured_skips_gateway_section`
- `test_gateway_listener_inject_approve_then_watcher_processes`
- `test_onboard_returning_user_menu_runs_correct_section`
- `test_headless_onboard_produces_profile_yaml_with_defaults`

### GREEN
Wire together: `onboard` → `profile.yaml` written → `approve` CLI → `operator_commands`
row → watcher cycle reads row → task transitions to `plan_approved`.

Requires watcher worker to poll `operator_commands` table (add to `watcher_worker.py`
processing loop).

### REFACTOR
- Remove any remaining `onboarding.yaml` references
- Consolidate `init_project.py` and `onboard.py` init paths (one calls the other)

### E2E (the full story)
```bash
tmp=$(mktemp -d) && git init "$tmp" --quiet
shux onboard --project "$tmp" --non-interactive
shux task create --project "$tmp" --title "First task"  # → t-xxxxx
shux task status --project "$tmp" --id t-xxxxx --status plan_proposed --actor claude-code --summary "plan"
shux approve --project "$tmp" t-xxxxx
shux watch --project "$tmp" --once   # watcher processes the approve command
shux contract --project "$tmp" | grep "plan_approved"
echo "full integration ok"
```

---

## Summary table

| Iter | Deliverable | New files | Tests |
|---|---|---|---|
| I1 | Prompt primitives | 2 | 8 |
| I2 | Section registry + shell | 1 (rewrite) | 6 |
| I3 | Section implementations | 1 + 1 refactor | 15 |
| I4 | Quick-setup + summary | 1 (extend) | 6 |
| I5 | operator_commands DAO | 2 | 6 |
| I6 | Gateway listener | 1 | 6 |
| I7 | Gateway wizard + CLI | 1 + 2 | 8 |
| I8 | Full integration | 1 | 5 |
