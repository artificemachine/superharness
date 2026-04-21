# Plan: `shux workflow` + Per-Project Autonomy

**Status:** plan_approved
**Owner:** claude-code
**Task ID:** `superharness-workflow-cmd`
**Target release:** v1.28.0
**Method:** TDD (RED → GREEN → REFACTOR per iteration)
**Consumer plan:** `~/DevOpsSec/morpheme/docs/plans/workflow-consume.md`

---

## Context

The default task lifecycle works for operators who drive every transition themselves. It does not work for project owners who want to say "AI runs this project, I just want to watch." The state machine has no notion of project-level policy.

What exists today (confirmed by exploration):
- 6 per-task workflow presets in `src/superharness/engine/lifecycle.py:34-68` (implementation, quick, discussion, review, approval, note) — each has its own dispatch gates. Good foundation.
- `profile.yaml` exists per-project with an `autonomy` field, but nothing reads it.
- State machine guards are hardcoded in 7 places across `next_action.py`, `task.py`, `lifecycle.py`, `delegate.py`, `inbox_enqueue.py`. Full custom flows are too much for this release.

What this release ships:
- Project-level autonomy toggle: `ai_driven` (default) / `oversight` / `hands_on`.
- TDD requirement toggle: `require_tdd` (default true), scoped to `implementation` and `review` workflows.
- Per-task stamping: `shux task create` copies the current profile policy onto the task. Changing the profile later affects new tasks only — existing tasks keep their stamped policy.
- `shux workflow` interactive CLI (+ flags) to edit policy.
- Schema v1.4 adapter-payload: `project_settings` top-level block + per-task `workflow` / `development_method` / `autonomy` / `require_tdd`.

What this release defers (as `superharness-custom-workflow` follow-up):
- User-defined statuses, custom transitions, custom gates
- AI classifier extended to pick `workflow` / `development_method` per task

Auth is not in scope. Morpheme runs locally on a trusted machine; identity without auth is social convention.

---

## Scope

**In:**
1. `profile.yaml` schema extension (`autonomy` formalized, `workflow.default_preset`, `workflow.require_tdd`).
2. Per-task policy stamping at `shux task create` time (reads profile, writes task fields).
3. `shux workflow` command — interactive + `--autonomy` / `--default-preset` / `--require-tdd` / `--show` / `--json` flags.
4. Auto-approve hook in `task.py` — `plan_proposed → plan_approved` when `task.autonomy == "ai_driven"`.
5. TDD field enforcement in `shux handoff-write` when `task.require_tdd && task.workflow in {implementation, review}`.
6. Adapter-payload schema v1.4:
   - Top-level `project_settings: { autonomy, workflow: { default_preset, require_tdd } }`
   - Per-task: `workflow`, `development_method`, `autonomy`, `require_tdd`
7. Docs: `docs/adapter-payload-spec.md` v1.4 section.
8. CHANGELOG entry + v1.28.0 release (PyPI + GitHub).

**Out (follow-up tasks):**
- Custom state machine (`superharness-custom-workflow`)
- Classifier picks workflow/method per task
- Per-task autonomy override via Morpheme UI
- Auth / multi-user identity

---

## Data model

`.superharness/profile.yaml`:

```yaml
# existing fields preserved
project_name: my-project
autonomy: ai_driven        # existing field, now formalized enum: ai_driven | oversight | hands_on
primary_agent: claude-code

# NEW section
workflow:
  default_preset: implementation  # one of: implementation | quick | discussion | review | approval | note
  require_tdd: true                # bool
```

`.superharness/contract.yaml` per-task entry adds:

```yaml
- id: some-task
  # existing fields...
  workflow: implementation          # already existed; enforced at create time
  development_method: tdd           # already existed
  autonomy: ai_driven               # NEW — stamped from profile at create
  require_tdd: true                 # NEW — stamped from profile at create
```

**Defaults when any field is absent at transition time:**
- `autonomy` → `ai_driven`
- `require_tdd` → `true`
- `workflow` → `quick` (existing default from `task.py`)

This means pre-existing tasks (created before this feature) inherit the new safe defaults at transition time. If a user wants the old no-autonomy behavior on existing tasks, they must explicitly stamp them.

---

## TDD Iterations

Each iteration is one commit: RED (failing tests) → GREEN (minimal impl) → REFACTOR (cleanup). Commits ship together in one PR.

### Iteration 1 — Profile schema + stamping at create

**Goal:** `shux task create` reads current profile and stamps `autonomy` / `require_tdd` onto the new task in `contract.yaml`.

**RED — `tests/unit/test_task_create_stamping.py` (new):**
- `test_create_stamps_ai_driven_when_profile_absent` — no profile.yaml → task has `autonomy=ai_driven`, `require_tdd=true`
- `test_create_stamps_profile_autonomy` — profile has `autonomy: oversight` → task has `autonomy=oversight`
- `test_create_stamps_profile_require_tdd` — profile has `workflow.require_tdd: false` → task has `require_tdd=false`
- `test_explicit_cli_flag_overrides_profile` — `shux task create --autonomy hands_on` overrides profile
- `test_existing_tasks_unchanged` — a second `shux task create` with different profile doesn't mutate prior tasks

**GREEN:**
- `src/superharness/commands/task.py` `create()`: after assembling the task dict, if `autonomy` not explicitly set, load profile, read `profile.get("autonomy", "ai_driven")`, stamp onto task dict. Same for `require_tdd` from `profile.get("workflow", {}).get("require_tdd", True)`.
- Add `--autonomy` / `--require-tdd` / `--no-require-tdd` CLI flags on `shux task create` for explicit override.

**REFACTOR:**
- Extract `_stamp_policy_from_profile(task_dict, project)` helper in `task.py` — one call site today, but will be reused by subtask creation and task update later.

**Files:**
- MODIFY: `src/superharness/commands/task.py` (create function, CLI parser)
- NEW: `tests/unit/test_task_create_stamping.py`

---

### Iteration 2 — Auto-approve hook on `plan_proposed`

**Goal:** when `shux task status --status plan_proposed` succeeds on a task with `autonomy=ai_driven`, the status automatically advances to `plan_approved`.

**RED — `tests/unit/test_task_autonomy_hook.py` (new):**
- `test_plan_proposed_auto_flips_to_plan_approved_when_ai_driven` — task.autonomy=ai_driven, transition plan_proposed → expect final status plan_approved in contract
- `test_plan_proposed_stays_when_oversight` — task.autonomy=oversight → expect status plan_proposed (human must approve)
- `test_plan_proposed_stays_when_hands_on` — task.autonomy=hands_on → expect status plan_proposed
- `test_no_recursion_beyond_one_step` — hook must not recurse plan_approved → in_progress automatically
- `test_ledger_logs_auto_approval` — ledger.md gets a line mentioning "auto-approved per task.autonomy=ai_driven"

**GREEN:**
- `src/superharness/commands/task.py` `status_update()`: after a successful transition where `new_status == "plan_proposed"` and task record has `autonomy == "ai_driven"`, recursively call `status_update(..., status="plan_approved", actor="ai-autonomy", summary="auto-approved per task autonomy setting", _recursion_guard=True)`.
- `_recursion_guard` kwarg prevents infinite loop.

**REFACTOR:**
- If other hooks emerge later (auto-verify on report_ready?), extract `_policy_post_hook(task, old_status, new_status)` dispatcher.

**Files:**
- MODIFY: `src/superharness/commands/task.py`
- NEW: `tests/unit/test_task_autonomy_hook.py`

---

### Iteration 3 — TDD enforcement in `handoff-write`

**Goal:** when a task has `require_tdd=true` AND `workflow in {implementation, review}`, `shux handoff-write --phase plan` rejects handoffs missing any of `tdd.red` / `tdd.green` / `tdd.refactor`.

**RED — `tests/unit/test_handoff_write_tdd.py` (new or extend existing):**
- `test_plan_rejected_when_require_tdd_and_tdd_fields_missing` — task.require_tdd=true, workflow=implementation, plan without tdd → exit 2, error mentions tdd.red/green/refactor
- `test_plan_accepted_when_require_tdd_false` — task.require_tdd=false → plan without tdd succeeds
- `test_plan_accepted_when_workflow_is_quick` — workflow=quick, even if require_tdd=true → plan without tdd succeeds (silently skipped)
- `test_plan_accepted_when_all_tdd_fields_present` — full TDD plan succeeds
- `test_error_message_includes_workflow_name` — error mentions the current workflow for clarity

**GREEN:**
- `src/superharness/commands/handoff_write.py`: before writing the handoff YAML when `phase == "plan"`, load the task record, check `task.require_tdd` and `task.workflow`. If TDD required and tdd fields empty, `_abort("error: --tdd-red/--tdd-green/--tdd-refactor are all required (task.require_tdd=true, workflow=<x>)", 2)`.

**REFACTOR:**
- None anticipated — single validation block.

**Files:**
- MODIFY: `src/superharness/commands/handoff_write.py`
- NEW: `tests/unit/test_handoff_write_tdd.py`

---

### Iteration 4 — `shux workflow` CLI

**Goal:** interactive + non-interactive CLI that reads/writes profile.yaml.

**RED — `tests/unit/test_workflow_cmd.py` (new):**
- `test_show_prints_current_settings` — `shux workflow --show` on empty profile prints defaults (ai_driven, implementation, require_tdd=true)
- `test_json_output_shape` — `--show --json` returns `{"autonomy":..., "workflow":{"default_preset":..., "require_tdd":...}}`
- `test_flag_sets_autonomy` — `--autonomy oversight` writes profile.yaml
- `test_flag_sets_default_preset` — `--default-preset quick` writes profile.yaml
- `test_flag_sets_require_tdd_true` / `_false` — `--require-tdd` / `--no-require-tdd`
- `test_invalid_autonomy_rejected` — `--autonomy invalid_value` → exit 2, error mentions valid values
- `test_invalid_preset_rejected` — `--default-preset bogus` → exit 2
- `test_interactive_flow_writes_profile` — simulate stdin with "1\n1\nY\n" → profile updated
- `test_interactive_skipped_on_non_tty` — non-TTY without flags → prints help and exits 0
- `test_preserves_existing_fields` — profile has `primary_agent: claude-code` → after `shux workflow --autonomy hands_on`, `primary_agent` still present

**GREEN:**
- `src/superharness/commands/workflow_cmd.py` (new) — command implementation. Use click (consistent with `config.py`) for flags.
- Interactive prompts via bare `input()` with `sys.stdin.isatty()` check (pattern from `init_project.py:50-102`).
- Reuse `_load_profile` / `_save_profile` from `commands/config.py`.
- Register in `src/superharness/cli.py` alongside `cmd_config`.

**REFACTOR:**
- If any validation logic (enum check for autonomy, preset) duplicates what `task create` does, extract to a shared `engine/policy.py` module.

**Files:**
- NEW: `src/superharness/commands/workflow_cmd.py`
- MODIFY: `src/superharness/cli.py` (register command)
- NEW: `tests/unit/test_workflow_cmd.py`

---

### Iteration 5 — Adapter-payload schema v1.4

**Goal:** `shux adapter-payload --json` emits `project_settings` at top level + per-task `workflow` / `development_method` / `autonomy` / `require_tdd`. `SCHEMA_VERSION` bumped to `"1.4"`.

**RED — extend `tests/unit/test_adapter_payload.py`:**
- `test_schema_version_is_1_4` — update existing assertions from "1.3" to "1.4"
- `test_project_settings_block_present` — top-level `project_settings` key exists
- `test_project_settings_defaults_when_profile_absent` — no profile.yaml → `project_settings.autonomy == "ai_driven"`, `workflow.default_preset == "implementation"`, `require_tdd == true`
- `test_project_settings_reflects_profile` — profile with custom values → payload reflects them
- `test_task_emits_workflow_and_development_method` — task with workflow=implementation, development_method=tdd → payload has both
- `test_task_emits_autonomy_and_require_tdd` — task with stamped autonomy → payload has it
- `test_pre_existing_task_defaults_when_unstamped` — task without autonomy field → payload shows ai_driven (safe default)

**GREEN:**
- `src/superharness/commands/adapter_payload.py`:
  - Bump `SCHEMA_VERSION = "1.4"`
  - Add `_load_project_settings(project_path)` that reads profile.yaml with defaults
  - Add `"project_settings"` key to `build_payload` return dict
  - In `_build_tasks`, emit `workflow`, `development_method`, `autonomy`, `require_tdd` per entry (with defaults)

**REFACTOR:**
- Extract task-entry-building helpers if the function grows; consistent with the v1.2/v1.3 additions.

**Files:**
- MODIFY: `src/superharness/commands/adapter_payload.py`
- MODIFY: `tests/unit/test_adapter_payload.py`
- MODIFY: `docs/adapter-payload-spec.md` — add v1.4 section with field reference

---

### Iteration 6 — Release prep

**Goal:** CHANGELOG, version bump, tag, PyPI publish.

**RED/GREEN:**
- Append CHANGELOG.md entry summarizing the feature
- Bump `pyproject.toml` version: `1.27.0 → 1.28.0`
- All iterations 1-5 tests pass: `python -m pytest tests/ -q`

**Files:**
- MODIFY: `CHANGELOG.md`
- MODIFY: `pyproject.toml`

---

## Verification (end-to-end on a throwaway project)

```bash
# 1. Default on new project
cd /tmp/ztest && git init && shux init
yq '.autonomy' .superharness/profile.yaml                  # ai_driven
yq '.workflow.require_tdd' .superharness/profile.yaml      # true

# 2. Interactive walk-through
shux workflow                                              # 3 prompts
yq '.autonomy' .superharness/profile.yaml

# 3. Flag-based update
shux workflow --autonomy oversight --no-require-tdd --show
yq '.autonomy' .superharness/profile.yaml                  # oversight

# 4. Per-task stamping (under oversight)
shux task create --id t-oversight --title "x" --workflow implementation
yq '.tasks[] | select(.id=="t-oversight") | .autonomy' .superharness/contract.yaml  # oversight

# 5. Change profile back to ai_driven, existing task unchanged
shux workflow --autonomy ai_driven
yq '.tasks[] | select(.id=="t-oversight") | .autonomy' .superharness/contract.yaml  # still oversight

# 6. New task stamps the new policy
shux task create --id t-ai --title "y" --workflow implementation
yq '.tasks[] | select(.id=="t-ai") | .autonomy' .superharness/contract.yaml         # ai_driven

# 7. Auto-approve on ai_driven
shux task status --id t-ai --status plan_proposed --actor claude-code --summary x
yq '.tasks[] | select(.id=="t-ai") | .status' .superharness/contract.yaml           # plan_approved

# 8. TDD enforcement (require_tdd defaults true on t-ai since profile=ai_driven)
# Turn require_tdd on globally so new task inherits
shux workflow --require-tdd
shux task create --id t-tdd --title "z" --workflow implementation
shux handoff-write --task t-tdd --phase plan --from owner --to claude-code --plan "x"
# expect: exit 2, error mentions tdd.red/green/refactor

# 9. TDD skipped for quick workflow
shux task create --id t-quick --title "q" --workflow quick
shux handoff-write --task t-quick --phase plan --from owner --to claude-code --plan "x"
# expect: exit 0

# 10. Schema v1.4 in payload
shux adapter-payload --json | jq '{schema_version, project_settings, example: .tasks[0]}'
# expect: schema_version=1.4, project_settings has autonomy/workflow, task has workflow+development_method+autonomy+require_tdd

# 11. Full test suite
python -m pytest tests/ -q    # all green
```

---

## Ship flow

1. Branch `feat/workflow-cmd` (already created).
2. Commit per iteration (1 through 6) on the branch — 6 commits.
3. `ALLOW_PUSH=1 git push -u origin feat/workflow-cmd`.
4. `gh pr create` with body summarizing all iterations.
5. Merge to main (with owner approval).
6. Cut v1.28.0 — tag, GitHub release, PyPI publish (follow existing release workflow).
7. Close `superharness-workflow-cmd` task.
8. Notify morpheme side that v1.28.0 is live so `workflow-consume` plan can start.
9. Queue follow-up task `superharness-custom-workflow` (plan_proposed) for user-defined state machine.
