# Adapter Payload Spec

**Status:** Implemented — `shux adapter-payload --json` ships in v1.16.0  
**Author:** Morpheme / Claude Code session 2026-04-12  
**Reference consumer:** Morpheme (`src/server/adapter.js`) — first consumer, drove the design  
**Implemented by superharness:** `src/superharness/commands/adapter_payload.py` (v1.16.0)

> This spec defines a stable JSON contract for any downstream renderer (TUI, web UI, IDE plugin, etc.). Morpheme is the reference consumer; the payload is intentionally generic. Text below mentions Morpheme frequently because it drove the design, but the contract is not Morpheme-specific.

---

## Why This Exists

Morpheme currently reads raw `.superharness/` files directly and normalizes them itself:

- Reads `contract.yaml` → parses tasks, maps lifecycle statuses to display statuses
- Reads `handoffs/*.yaml` → structures per-task handoff history
- Reads `ledger.md` → parses timestamp/task/description format
- Reads `inbox.yaml`, `failures.yaml`, `decisions.yaml` → loads as-is

This means Morpheme knows too much about the superharness file layout and protocol. Every time the protocol changes (new status, new field, new file format), Morpheme breaks.

**The fix:** superharness should own normalization. Morpheme should be a pure renderer over a stable JSON payload.

---

## What Morpheme Needs

Implement one new CLI command:

```
shux adapter-payload --json [--project PATH]
```

This command reads the current project state and returns a single JSON object to stdout. Morpheme calls this instead of reading files directly.

**Morpheme's `adapter.js`** already detects and uses this command automatically:
- If `shux adapter-payload --json` succeeds and returns `schema_version: "1.0"` → Morpheme uses it
- If the command fails or is not found → Morpheme falls back to reading raw files (`rawParser.js`)

Zero breaking changes. The fallback keeps working indefinitely until the command ships.

**Performance requirement:** the command must complete in < 500ms. Morpheme calls it on every file-change event.

---

## Payload Schema (v1.2)

### Version history

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-04-12 | Initial stable payload. |
| 1.1 | 2026-04-16 | Added `model_tier` + `resolved_model: {id, label}` per task and subtask (backwards-compatible). |
| 1.2 | 2026-04-18 | Added `classifier`, `decomposer`, `retry` blocks per task. Additive — v1.1 consumers ignore the new fields. |
| 1.2 | 2026-04-20 | Added `status` to each subtask entry, resolved by inheritance: a subtask reports `status: done` whenever its parent task is in a terminal-done state (`done` or `review_passed`), unless the subtask carries an explicit non-pending status. Additive — existing v1.0/v1.1 consumers ignore the new field. |

### Annotated Example

The block below uses `//` comments for documentation. Strip them before parsing — they are not valid JSON.

```jsonc
{
  // Required. Consumers should validate this >= "1.0". 1.2 adds
  // classifier/decomposer/retry blocks; 1.1 adds resolved_model.
  "schema_version": "1.2",

  // From contract.yaml `id:` field
  "contract_id": "my-project",

  // From contract.yaml `goal:` field
  "goal": "Build the new auth system",

  // All tasks in the contract, in declaration order
  "tasks": [
    {
      // Stable identifier — must match blocked_by references across tasks
      "id": "task-implement-login",

      "title": "Implement login endpoint",

      // Raw superharness lifecycle status (see display_status mapping table)
      "status": "in_progress",

      // Normalized display status for Morpheme rendering (computed by superharness)
      "display_status": "generating",

      // Hex border color for the node (derived from display_status — see mapping table)
      "color": "#4e8098",

      "owner": "claude-code",

      // Accumulated token cost in USD. null if not tracked.
      "cost": 0.023,

      // IDs of tasks this task depends on.
      // Normalized from YAML `dependency:` (scalar string) → array.
      "blocked_by": [],

      // Human-readable effort estimate. Values: "low" | "medium" | "high" | null
      "effort": "medium",

      // Verbatim from contract.yaml `acceptance_criteria:` list
      "acceptance_criteria": [
        "POST /auth/login returns 200 + JWT on valid credentials",
        "Returns 401 for wrong password"
      ],

      // All handoffs for this task, oldest first
      "handoffs": [
        {
          // "plan" = planning phase, "report" = completion report
          "phase": "plan",

          "from": "owner",
          "to": "claude-code",
          "date": "2026-04-10T14:22:00Z",

          // Task status at the time this handoff was written
          "status": "plan_approved",

          // One-line summary (plan phase)
          "summary": "Build POST /auth/login with JWT response",

          // Full plan text (plan phase only)
          "plan": "1. Add route handler\n2. Add JWT signing\n3. Add tests",

          // TDD block (plan phase only). All three subfields present when block exists.
          "tdd": {
            "red": "Write failing test for 401 on bad credentials",
            "green": "Implement handler until tests pass",
            "refactor": "Extract token logic to auth service"
          },

          // Open risks or questions identified at plan time (plan phase only)
          "risks": "JWT secret rotation not yet handled",

          // Outcome items are null/empty on plan handoffs
          "outcomes": [],
          "tests_passed": null,
          "verified": false
        },
        {
          "phase": "report",
          "from": "claude-code",
          "to": "owner",
          "date": "2026-04-11T09:15:00Z",
          "status": "report_ready",

          // Narrative of what was done (report phase only)
          "outcome": "Login endpoint implemented with JWT. All tests passing.",

          // Context for the next session or reviewer (report phase only)
          "context": "Used HS256. Secret read from env. No refresh tokens yet.",

          // Structured outcome items. status values: "pass" | "fail" | "skip"
          "outcomes": [
            { "criterion": "POST /auth/login returns 200 + JWT", "status": "pass", "detail": "" },
            { "criterion": "Returns 401 for wrong password", "status": "pass", "detail": "" }
          ],

          // Files modified during this task
          "files_changed": ["src/routes/auth.py", "tests/test_auth.py"],

          // true = passed, false = failed, null = not run
          "tests_passed": true,

          // e.g. ["unit", "integration", "e2e"]
          "test_types": ["unit", "integration"],

          // true once owner has run `shux verify`
          "verified": false
        }
      ]
    }
  ],

  // Directed edges for the dependency graph
  "edges": [
    {
      // Root tasks (no blocked_by) get source "__contract__" — reserved sentinel
      "source": "__contract__",
      "target": "task-implement-login",
      "type": "contract"
    },
    {
      // Derived from blocked_by: task-write-docs depends on task-implement-login
      "source": "task-implement-login",
      "target": "task-write-docs",
      "type": "dependency"
    }
  ],

  // Activity log normalized from ledger.md. Newest entry first.
  "ledger": [
    {
      "timestamp": "2026-04-11T09:15:00Z",
      "type": "task",       // "task" | "session" | "file" | "unknown"
      "task": "task-implement-login",
      "description": "report submitted"
    },
    {
      "timestamp": "2026-04-10T14:22:00Z",
      "type": "session",
      "description": "session-stop: claude-code"
    }
  ],

  // From failures.yaml — one entry per dispatch failure
  "failures": [
    {
      "task": "task-write-docs",
      "severity": "minor",  // "minor" | "major" | "critical"
      "error_snippet": "AssertionError: expected 3 sections, got 2",
      "patterns": ["AssertionError"],
      "agent": "claude-code",
      "date": "2026-04-09T00:00:00Z"
    }
  ],

  // From decisions.yaml — ADR-lite records
  "decisions": [
    {
      "id": "ADR-001",
      "what": "Use HS256 for JWT signing",
      "why": "Simpler than RS256 for single-service setup",
      "alternatives": ["RS256", "EdDSA"],
      "status": "accepted",  // "accepted" | "superseded" | "deprecated"
      "by": "owner",
      "date": "2026-04-10"
    }
  ],

  // From inbox.yaml — active dispatch queue items
  "inbox": [
    {
      "id": "inbox-001",
      "task": "task-write-docs",
      "status": "pending",  // "pending" | "launched" | "running" | "paused" | "done" | "failed"
      "to": "claude-code",
      "priority": 2,         // lower = higher priority
      "retry_count": 0,
      "max_retries": 3,
      "created_at": "2026-04-11T10:00:00Z"
    }
  ],
  "agent_pulse": {
    "task_id": "task-write-docs",
    "agent": "claude-code",
    "status": "running",    // "running" | "waiting_input" | "paused"
    "last_seen": "2026-04-12T10:05:00Z",
    "message": "writing unit tests",
    "pid": 1234
  }
}
```

---

## Field Reference

### Top Level

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `"1.0"` | Must be exactly `"1.0"` — Morpheme rejects any other value |
| `contract_id` | string | Contract identifier (from `contract.yaml` `id:`) |
| `goal` | string | One-line project goal |
| `tasks` | Task[] | All tasks in contract order |
| `edges` | Edge[] | All directed edges (contract → task, task → task) |
| `ledger` | LedgerEntry[] | Activity log, newest first |
| `failures` | Failure[] | Failure records from `failures.yaml` |
| `decisions` | Decision[] | ADR-lite records from `decisions.yaml` |
| `inbox` | InboxItem[] | Active dispatch queue from `inbox.yaml` |
| `agent_pulse` | AgentPulse \| null | Current liveness signal from the running agent. `null` when no pulse file exists. |

---

### AgentPulse

Written by a running agent to `.superharness/agent-pulse.yaml` via `shux agent-pulse write`.

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string \| null | Task being executed |
| `agent` | string \| null | Agent identifier (`claude-code`, `codex-cli`, etc.) |
| `status` | string \| null | Agent's self-reported status (`running`, `waiting_input`, `paused`) |
| `last_seen` | string | ISO 8601 timestamp of last pulse write |
| `message` | string \| null | Optional human-readable status message |
| `pid` | integer \| null | Process ID of the running agent |

---

### Task

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Task ID. Must match `blocked_by` references on other tasks. |
| `title` | string | Human-readable title |
| `status` | string | Raw superharness lifecycle status (see mapping table) |
| `display_status` | string | Normalized Morpheme display status — see mapping table |
| `color` | string | Hex border color, derived from `display_status` |
| `owner` | string | Agent or person responsible (`claude-code`, `codex-cli`, `owner`) |
| `cost` | number? | Accumulated token cost in USD. `null` if untracked. |
| `blocked_by` | string[] | IDs this task depends on. Normalized from YAML `dependency:` field (see note). |
| `model_tier` | string? | Cost/capability bucket chosen by the orchestrator (`mini` \| `standard` \| `max` \| other). Null when unset. |
| `resolved_model` | `{id, label}`? | Concrete model descriptor resolved from `(owner, model_tier)` via the adapter manifest. Absent when `model_tier` is empty/null. See **Resolved model** section below. |
| `effort` | string? | `"low"` \| `"medium"` \| `"high"` \| `"xhigh"` \| `"max"` \| `null` |
| `classifier` | object | v1.2+. Pipeline classifier result. Always present; defaults when not set in YAML. See **Pipeline blocks (v1.2)** below. |
| `decomposer` | object | v1.2+. Orchestrator decomposition result. Always present; defaults when not set in YAML. |
| `retry` | object | v1.2+. Retry state. Always present; defaults to `{count: 0, escalation_history: []}`. |
| `acceptance_criteria` | string[] | List of acceptance criteria strings |
| `handoffs` | Handoff[] | All handoffs for this task, oldest first |

> **Normalization note:** `contract.yaml` stores task dependencies as `dependency: <task-id>` (a scalar string). The adapter normalizes this to `blocked_by: ["<task-id>"]` (an array). Tasks with multiple blockers may use a YAML sequence — normalize to array in both cases.
>
> **Null-sentinel collapse:** `blocked_by: none`, `blocked_by: null`, `blocked_by: ~`, `blocked_by: ""`, and `blocked_by: []` all normalize to the empty list `[]`. Inside a sequence, any null-sentinel items are filtered out (e.g. `[none, iter-0, null]` → `["iter-0"]`). This is enforced by `superharness.engine.normalization.normalize_blocked_by` and used by both `shux adapter-payload --json` and the shux dashboard renderer.

---

### Subtask status (v1.2, 2026-04-20)

Each entry in a task's `subtasks[]` carries a `status` field with the effective lifecycle state, resolved as follows:

1. If the subtask's raw `status` in `contract.yaml` is set to anything other than `pending`, emit it as-is.
2. Otherwise, if the parent task's `status` is a terminal-done state (`done` or `review_passed`), emit `"done"` (inheritance).
3. Otherwise, emit `"pending"` (or the raw value if non-empty).

This lets Morpheme and other adapters render accurate status badges without duplicating the state-machine rules client-side. Subtasks never individually flow through `in_progress` / `report_ready` — the parent closes them as a unit — so this resolution is sufficient to distinguish pending planning artifacts from work covered by a closed parent.

### Resolved model (v1.1+)

Every task and subtask with a non-empty `model_tier` carries a `resolved_model` field of the shape:

```json
{
  "id":    "claude-sonnet-4-6",
  "label": "Sonnet 4.6"
}
```

- **`id`** — the concrete model identifier used by SDK / API calls.
- **`label`** — the human-facing name that UI clients render (badges, tooltips, cards).

Resolution is a two-step lookup:

1. Load the adapter manifest for the task's `owner` (e.g. `claude-code.yaml`).
2. Look up `model_tier` in the manifest's `model_tiers` table.

If the owner or tier is unknown, the payload falls back to `{id: <tier>, label: <tier>}` so clients always receive a well-formed object.

**Manifest schema:** `model_tiers` entries accept two forms for backwards compatibility:

```yaml
# New form (preferred) — explicit id + label pair:
model_tiers:
  mini:     { id: claude-haiku-4-5-20251001, label: "Haiku 4.5"  }
  standard: { id: claude-sonnet-4-6,         label: "Sonnet 4.6" }
  max:      { id: claude-opus-4-6,           label: "Opus 4.6"   }

# Legacy form — scalar string, shimmed to {id: val, label: val}:
model_tiers:
  standard: sonnet   # → {id: "sonnet", label: "sonnet"}
```

Both forms load via `superharness.engine.adapter_registry.load_manifest`, which always produces normalized `{id, label}` dicts. The canonical resolver is `resolve_model(owner, tier) -> {id, label}`.

**Backwards compatibility:** `model_tier` string remains in the payload alongside `resolved_model`. Schema 1.0 consumers (e.g. Morpheme's pre-1.1 path) can ignore the new field and keep reading `model_tier` directly.

---

### Pipeline blocks (v1.2+)

Three new objects are always present on each task entry. When the pipeline has not run (most existing tasks), they carry safe defaults.

#### `classifier`

| Field | Type | Description |
|---|---|---|
| `invoked` | bool | `true` when the classifier ran for this task |
| `decided_by` | string? | `"heuristic"` or `"sonnet-4-6"` (LLM fallback) |
| `heuristic_reason` | string? | Which rule fired (e.g. `"title matches OPUS_KEYWORDS"`) |
| `cost_usd` | number? | Classifier cost. `null` for heuristic path (free); ~0.002 for LLM path. |
| `duration_ms` | number? | Wall time in milliseconds. |

#### `decomposer`

| Field | Type | Description |
|---|---|---|
| `invoked` | bool | `true` when the Opus orchestrator decomposed this task |
| `model` | string? | `"claude-opus-4-6"` (default) or `"claude-opus-4-7"` (fallback) |
| `rationale` | string? | LLM-generated split rationale |
| `cost_usd` | number? | Decomposer call cost in USD |
| `duration_ms` | number? | Wall time in milliseconds |
| `subtask_count` | integer | Number of subtasks generated (0 when not invoked) |

#### `retry`

| Field | Type | Description |
|---|---|---|
| `count` | integer | How many times this task has been retried (0 = never) |
| `escalation_history` | string[] | Ordered list of models used in prior attempts (e.g. `["claude-sonnet-4-6", "claude-opus-4-6"]`) |

**When to bump a model:** update `id` and `label` together in the adapter manifest. Consumers display `label`; `id` is only used for SDK dispatch. Do not bump `schema_version` for model bumps — only bump it when adding/removing fields or changing shapes.

---

### display_status + Color Mapping

This mapping currently lives in Morpheme's `rawParser.js`. Once `shux adapter-payload` ships, superharness owns it and `rawParser.js` is deleted. Extracted from `rawParser.js` as of 2026-04-12.

| superharness `status` | `display_status` | `color` |
|-----------------------|-----------------|---------|
| `todo` | `pending` | `#6b7280` |
| `plan_proposed` | `pending` | `#c8922a` |
| `plan_approved` | `generating` | `#4e8098` |
| `in_progress` | `generating` | `#4e8098` |
| `report_ready` | `validating` | `#8b5cf6` |
| `review_requested` | `validating` | `#8b5cf6` |
| `review_passed` | `validating` | `#10b981` |
| `review_failed` | `failed` | `#ef4444` |
| `done` | `done` | `#10b981` |
| `failed` | `failed` | `#ef4444` |
| `stopped` | `failed` | `#ef4444` |
| `waiting_input` | `paused` | `#f59e0b` |
| `paused` | `paused` | `#f59e0b` |

> When new lifecycle statuses are added to superharness, update `status_map.py`. Morpheme needs no code change.

---

### Edge

| Field | Type | Description |
|-------|------|-------------|
| `source` | string | Source task ID, or `"__contract__"` for root tasks |
| `target` | string | Target task ID |
| `type` | `"contract"` \| `"dependency"` | `contract` = root task (no blockers); `dependency` = from `blocked_by` |

> `"__contract__"` is a reserved sentinel for the orchestrator root node. Every task with an empty `blocked_by` list gets a `contract` edge from `"__contract__"`.

---

### Handoff

Plan and report handoffs share a common envelope. Phase-specific fields are marked.

| Field | Type | Phase | Notes |
|-------|------|-------|-------|
| `phase` | `"plan"` \| `"report"` | both | |
| `from` | string | both | Sending agent |
| `to` | string | both | Receiving agent |
| `date` | ISO 8601 | both | |
| `status` | string | both | Task status at time of handoff |
| `summary` | string? | plan | One-line summary |
| `plan` | string? | plan | Full plan text |
| `tdd` | `{ red, green, refactor }`? | plan | All three subfields present when block exists |
| `risks` | string? | plan | Open risks or questions |
| `outcome` | string? | report | Narrative of what was done |
| `context` | string? | report | Context for next session or reviewer |
| `outcomes` | OutcomeItem[]? | report | `{ criterion: string, status: "pass"\|"fail"\|"skip", detail: string }` |
| `files_changed` | string[]? | report | Modified files. `files_touched` is an accepted alias. |
| `tests_passed` | boolean? | report | `true` = all passed, `false` = failures, `null` = not run |
| `test_types` | string[]? | report | e.g. `["unit", "integration"]` |
| `verified` | boolean | both | `true` once owner runs `shux verify` |

---

### LedgerEntry

Normalized from `ledger.md`. The raw format is `TIMESTAMP | TASK | description` — the adapter parses and types each line.

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 | |
| `type` | `"task"` \| `"session"` \| `"file"` \| `"unknown"` | `task` = task lifecycle event; `session` = session-start/stop; `file` = file write |
| `task` | string? | Task ID for `type: "task"` entries |
| `agent` | string? | Agent name for `type: "session"` and `type: "file"` entries |
| `description` | string | Human-readable message |

---

### Failure

From `failures.yaml`. One entry per dispatch failure.

| Field | Type | Description |
|-------|------|-------------|
| `task` | string | Task ID that failed |
| `severity` | `"minor"` \| `"major"` \| `"critical"` | |
| `error_snippet` | string | First line(s) of error output |
| `patterns` | string[] | Matched error pattern labels (e.g. `["AssertionError", "timeout"]`) |
| `agent` | string | Agent that was running |
| `date` | ISO 8601 | |

---

### Decision

From `decisions.yaml`. ADR-lite records written by either agent or owner.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Short kebab ID (e.g. `"ADR-001"`) |
| `what` | string | Decision title |
| `why` | string | Rationale |
| `alternatives` | string[] | Options considered but rejected |
| `status` | `"accepted"` \| `"superseded"` \| `"deprecated"` | |
| `by` | string | Who made the decision (`claude-code`, `codex-cli`, `owner`) |
| `date` | `YYYY-MM-DD` | |

---

### InboxItem

From `inbox.yaml`. Active dispatch queue.

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Inbox item ID |
| `task` | string | Task ID this item dispatches |
| `status` | `"pending"` \| `"launched"` \| `"running"` \| `"paused"` \| `"done"` \| `"failed"` | |
| `to` | string | Target agent |
| `priority` | integer | Lower = higher priority |
| `retry_count` | integer | How many times this item has been retried |
| `max_retries` | integer | Retry limit before marking failed |
| `created_at` | ISO 8601 | |

---

## What Morpheme Stops Doing When This Ships

Once `shux adapter-payload --json` is implemented and verified:

1. **`rawParser.js` is deleted** — all file parsing logic goes away entirely
2. **`watchTargets.js` simplifies** — only needs to watch for changes that trigger a re-call of the adapter (or watch a single cached output file if superharness writes one)
3. **Status mapping is gone from Morpheme** — `display_status` and `color` come pre-computed in the payload
4. **Handoff file parsing is gone from Morpheme** — superharness assembles the per-task handoff list and normalizes field names
5. **Ledger parsing is gone from Morpheme** — superharness normalizes the raw `ledger.md` line format into typed `LedgerEntry` objects
6. **Morpheme's server becomes a thin WebSocket bridge** — it runs `shux adapter-payload --json`, parses the result, and pushes it to the browser. No protocol knowledge required.

---

## Suggested Implementation Location in superharness

```
superharness/
  commands/
    adapter_payload.py     ← shux adapter-payload --json entrypoint
  adapter/
    __init__.py
    payload_builder.py     ← assembles the full JSON payload from all sources
    status_map.py          ← display_status + color mapping (extracted from Morpheme)
    handoff_loader.py      ← scans handoffs/*.yaml, groups by task, sorts by date
    ledger_parser.py       ← parses ledger.md lines into typed LedgerEntry objects
```

The `shux adapter-payload` command must:
- Accept `--json` flag (default output format, included for explicitness)
- Accept `--project PATH` (default: cwd)
- Exit 0 on success, non-zero on any parse error
- Write JSON to stdout only; any warnings go to stderr
- Complete in < 500ms for contracts up to ~200 tasks

---

## Migration Plan

1. **Implement `shux adapter-payload --json`** in superharness using the schema above.

2. **Test against Morpheme** — `adapter.js` auto-detects the command. Run `morpheme start` against a live project and verify the graph renders correctly with the new payload path.

3. **Add `schema_version` bump policy** — any breaking field change increments `schema_version`. Morpheme validates `schema_version === "1.0"` before accepting. Old schema versions should have a deprecation window of at least one release cycle.

4. **Delete `rawParser.js`** from Morpheme once all installations have migrated (or after the fallback window closes).

---

## Open Questions

1. **Caching** — for contracts with 200+ tasks and deep handoff histories, a cold parse on every file-change event may exceed 500ms. Options:
   - `--since TIMESTAMP`: Morpheme passes last-received timestamp; superharness returns only changed tasks/entries
   - Write `.superharness/adapter-cache.json` on each change; Morpheme reads the file directly instead of invoking the CLI

2. **Streaming** — long-term, a streaming JSON or SSE endpoint would eliminate the polling model entirely. The current adapter model (CLI invocation on each change) is a deliberate step toward that without requiring a persistent process today.

3. **Versioning** — define a concrete deprecation policy before v2.0: e.g. "Morpheme supports current and one prior major schema version." The `schema_version` field allows this without breaking older installs.

4. **Multi-project** — Morpheme currently connects to one project at a time. If it ever needs to aggregate across multiple projects, `adapter-payload` should support `--projects PATH,PATH,...` and return a top-level array of payloads, each with its own `contract_id` and `schema_version`.
