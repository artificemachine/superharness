# Absorb Agent Toolkit Features — TDD Implementation Plan

> **STATUS: ALL 6 ITERATIONS IMPLEMENTED (2026-05-05)**
> 151 tests, all modules wired, dashboard integrated.
> See `docs/IMPLEMENTATION-status.md` for remaining work.

Source: `docs/AUDIT-agent-toolkit-superharness-adaptation.md`

## Rule

> Integrate into superharness core when it improves contract, handoff, dispatch, or observability.
> Connect through adapters when it's about interoperability with another runtime.
> Never make Pi or Hermes a hard dependency.

## What stays OUT (optional adapters)

These are separate services superharness connects to, never absorbs:
- Hermes messaging gateway, voice, memory provider
- Pi TypeScript TUI runtime
- Any coupling that would break superharness if Pi/Hermes are absent

---

## Iteration 1: Tool-loop guardrails (from Hermes) ✅ DONE

**What**: Detect when an agent loops on the same tool/action without progress.
**Why**: Prevents agents from burning tokens on infinite loops. Directly improves dispatch reliability.

**TDD**:
- RED: Test that a task with 5 consecutive identical tool calls is flagged as `blocked` with reason "loop detected"
- GREEN: Add `_detect_agent_loop()` to `inbox_watch.py` — checks launcher log for repeated patterns within a window
- REFACTOR: Extract pattern detection into `engine/loop_detector.py`

**Files**: `engine/loop_detector.py`, `commands/inbox_watch.py`, tests ✅

---

## Iteration 2: `shux handoff generate` (from Pi) ✅ DONE

**What**: Generate a structured handoff from the current session state using Pi's summary shape (compact: what was done, what remains, decisions made, next steps).
**Why**: Improves handoff quality between agent sessions. Currently handoffs are manual.

**TDD**:
- RED: Test that `shux handoff generate --task <id>` creates a handoff YAML with mandatory fields (summary, scope, acceptance, risks, artifacts)
- GREEN: Implement `shux handoff generate` command — reads contract state, ledger, and latest handoff to compose a structured summary
- REFACTOR: Extract summary composition into `engine/handoff_generator.py`

**Files**: `commands/handoff_generate.py`, `engine/handoff_generator.py`, tests ✅

---

## Iteration 3: FTS-backed recall (from Hermes) ✅ DONE

**What**: Full-text search over `.superharness/state.sqlite3` for past handoffs, failures, decisions, and ledger entries.
**Why**: Current `shux recall` searches YAML files. SQLite FTS5 gives instant search over all history.

**TDD**:
- RED: Test that text search over handoffs returns matching entries ranked by relevance
- GREEN: Add FTS5 virtual tables to SQLite schema (migration v6) — index handoffs, failures, decisions, ledger
- REFACTOR: Replace YAML grep in `recall.py` with SQLite FTS queries

**Files**: `engine/db.py` (migration v6), `engine/recall.py`, tests ✅

---

## Iteration 4: JSONL event stream (from both) ✅ DONE

**What**: Write structured JSONL events for every lifecycle transition, dispatch, failure, and discussion event. Dashboards and external clients tail the stream.
**Why**: Real-time observability without polling SQLite. Enables external integrations.

**TDD**:
- RED: Test that a task status change writes a JSONL event with `{type, task_id, from_status, to_status, timestamp}`
- GREEN: Add `engine/event_stream.py` — appends to `.superharness/events.jsonl` on every state write
- REFACTOR: Wire into `state_writer.set_task_status` and lifecycle reconciler

**Files**: `engine/event_stream.py`, `engine/state_writer.py`, tests ✅

---

## Iteration 5: Adapter policy gates (from Hermes) ✅ DONE

**What**: Per-agent policy gates — max cost, allowed actions, loop limits, permission bridging.
**Why**: Prevents runaway agents. Currently only global budget exists with no per-agent controls.

**TDD**:
- RED: Test that an agent exceeding its per-agent cost limit is blocked from further dispatch
- GREEN: Add `engine/policy_gate.py` — reads per-agent limits from `adapter_manifests/<agent>.yaml`
- REFACTOR: Integrate into watcher dispatch budget check

**Files**: `engine/policy_gate.py`, `adapter_manifests/`, tests ✅

---

## Iteration 6: Skill curation + usage insights (from Hermes) ✅ DONE

**What**: Track which skills are used by which agents, success/failure rates, and surface insights.
**Why**: Optimize skill selection. Currently no metrics on skill effectiveness.

**TDD**:
- RED: Test that after dispatch, skill usage is recorded with `{skill, agent, task, outcome}`
- GREEN: Add `engine/skill_metrics.py` — reads launcher logs for skill invocations, stores in SQLite
- REFACTOR: Add dashboard panel for skill insights

**Files**: `engine/skill_metrics.py`, `scripts/dashboard-ui.py`, `scripts/dashboard.html`, tests ✅

---

## Security note

`.superharness/state.sqlite3` and WAL files are now in `.gitignore` — runtime state must never be committed.
The JSONL event stream should also be gitignored.
