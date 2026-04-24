# Gemini Review: SuperHarness Architecture & Health Audit

**Verdict:** Changes Requested

The core primitives of the project (file-native protocol, append-only handoff ledger, and adapter manifests) are architecturally sound. However, the implementation has significantly drifted from the intended design, resulting in a project state that is currently non-functional in key areas.

## Critical Issues

### 1. Protocol Corruption (`contract.yaml`)
The `.superharness/contract.yaml` file is currently invalid YAML.
- **Evidence:** Around line 1960, the file switches from an object structure to a root-level list (`- id: ...`).
- **Impact:** `python -m superharness contract` and other CLI tools fail to parse the project state, effectively bricking the harness.

### 2. Broken Daemon Process
The daemon command attempts to launch a non-existent module.
- **Evidence:** `src/superharness/commands/daemon.py:100` calls `superharness.commands.watch`. No such module exists; the actual implementation is `superharness.commands.inbox_watch`.
- **Impact:** `shux daemon start` reports success while the background process immediately crashes.

---

## Major Technical Debt

### 1. PID Schema Collision
There is a high-severity collision on the `.superharness/daemon.pid.json` state file.
- **Daemon Command:** Expects `{"pid": <int>, ...}`.
- **Operator Engine:** Writes `{"operator_pid": <int>, "dashboard_port": <int>, ...}`.
- **Impact:** The Dashboard cannot be discovered by the CLI, and the Daemon cannot reliably stop or monitor the Operator.

### 2. Model Router API Mismatch
The auto-dispatch logic is broken due to a signature mismatch.
- **Caller:** `auto_dispatch.py` passes `(task_dict, project_dir=...)`.
- **Definition:** `model_router.py:classify_task` expects `(title, criteria, files, previously_failed)`.
- **Impact:** An exception is raised and swallowed, causing all tasks to default to `claude-code/standard` regardless of complexity or cost constraints.

### 3. Schema vs. Logic Drift
The `TaskStatus` enum in `src/superharness/engine/schemas.py` is missing lifecycle states that are used as canonical in the engine (`next_action.py`).
- **Missing States:** `pending_user_approval`, `review_requested`, `review_failed`, and `stopped`.
- **Impact:** Runtime validation fails when these legitimate states are encountered.

### 4. Fail-Open Dependency Resolution
The inbox engine fails open on errors.
- **Evidence:** `src/superharness/engine/inbox.py` catches all exceptions during dependency checks and returns `True`.
- **Impact:** If a contract is malformed, blocked tasks are dispatched prematurely, leading to race conditions and agent confusion.

---

## Architecture & Hygiene

- **Validation:** `engine/validate.py` ignores the Pydantic protocol models, preferring raw dict manipulation. This undercuts the "type-safe protocol" goal.
- **Git Hygiene:** Runtime files (`daemon.pid.json`, `trace.jsonl`, `.lock.d/`) are leaking into the repository because they are missing from `.superharness/.gitignore`.

## Summary Recommendation
The project requires an immediate **consolidation and stabilization phase**. Priority should be given to fixing the YAML parsing, unifying the PID state schema, and synchronizing the lifecycle Enums across the engine and schemas.
