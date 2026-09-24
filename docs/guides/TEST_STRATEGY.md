# Test Strategy — superharness Overlay

**Date:** 2026-05-25
**Status:** proposal
**Base:** Obsidian vault → `notes/tests/Testing Strategy.md`

> This is the superharness-specific overlay. The base strategy defines all test categories. This document defines which are **mandatory** for PR merge, why, and the file layout.

## Why this exists

Today (2026-05-25) we found 8 bugs in a single session. Every bug passed its unit tests but failed at integration boundaries. The test suite has 3,500+ tests but only covers **functions in isolation**. Zero coverage of:

- Multi-agent lifecycle flows (create → dispatch → fail → retry → advance)
- Cross-component state transitions (inbox → task → discussion → GC)
- Contract enforcement (manifest declares `supports_effort: false` → launcher ignores `--effort`)
- Failure injection (agent crash, DB error, rate limit)

This document defines **mandatory test categories** — tests that must exist and pass before any PR merges.

---

## Category 1 — SMOKE (`tests/smoke/`)

**Required: YES. Blocking on fail.**

| Test | Covers |
|------|--------|
| `shux --help` exits 0 | CLI loads |
| `shux contract` returns tasks | SQLite connection |
| `shux status` prints dashboard | Watcher connected |
| Watcher heartbeat written | Daemon alive |
| Import all engine modules | No import errors |

**Rule:** must run in < 5 seconds. If any fail, the PR is broken — do not merge.

---

## Category 2 — UNIT (`tests/unit/`)

**Required: YES. Blocking on fail.**

| Test | Covers |
|------|--------|
| Pure functions (no I/O) | Logic correctness |
| DAO operations (with in-memory DB) | Data access |
| Schema validation | Pydantic models |
| Command parsing | CLI argument handling |
| Failure classification | Pattern matching |

**Rule:** one test per function/method. Mock external dependencies (subprocess, network). Run in CI.

---

## Category 3 — INTEGRATION (`tests/integration/`)

**Required: YES. Blocking on fail. Status: Implemented — 255 tests.**

| Test | Covers |
|------|--------|
| **Lifecycle flow** — create → classify → delegate → retry → close | Task lifecycle end-to-end with SQLite |
| **Discussion flow** — start → dispatch rounds → submit → consensus → close | Multi-agent coordination |
| **Orchestrator flow** — task with >3 criteria → decompose → dispatch subtasks | Auto-orchestrate default path |
| **GC flow** — create orphan items → wait → GC cleans them | All 7 GC functions |
| **Launcher contract** — delegate to each agent, verify flags passed correctly | `--effort`, `--model`, `--yolo` propagation |
| **State transition** — every lifecycle status transition validates | `next_action.py` graph |

**Rule:** each test exercises 2+ components together with real SQLite DB. No mocking of `get_connection` — use in-memory or temp file DB.

---

## Category 4 — STATE MACHINE (`tests/state_machine/`)

**Required: YES. Blocking on fail. Status: Implemented — 325 tests.**

The task lifecycle has 16 statuses with legal transitions defined in `next_action.py`. Every transition must be tested:

| Test | Covers |
|------|--------|
| All legal transitions succeed | `validate_status_transition` accepts valid moves |
| All illegal transitions fail | `validate_status_transition` rejects invalid moves |
| Every status has a timeout rule | `lifecycle_rules.py` fires on schedule |
| `waiting_input` → archived after 30 min | GC timeout works |
| `in_progress` + dead PID → failed | Zombie reconciler |
| Discussion round lifecycle | `active` → `consensus` → `closed` (and failure paths) |

**Rule:** generate tests from the transition graph. If a new status is added, its transitions must be tested before merge.

---

## Category 5 — CHAOS / FAILURE INJECTION (`tests/chaos/`)

**Required: RECOMMENDED. Non-blocking but warns.**

| Test | Covers |
|------|--------|
| Agent subprocess killed mid-dispatch | Zombie reconciler recovers |
| SQLite WAL lock contention | Transaction retry works |
| DB file deleted during operation | Graceful fallback, no crash |
| All orchestrator models fail | Falls back to standard dispatch |
| Rate limit exhaustion | Retry budget respected, not infinite loop |

**Rule:** run weekly or on-demand. Not in CI (too slow). Failure here means the system degrades, not breaks.

---

## Category 6 — CONTRACT (`tests/contract/`)

**Required: YES. Blocking on fail. Partially exists.**

| Test | Covers |
|------|--------|
| Every adapter manifest field matches launcher behavior | `supports_effort` → `--effort` passed/ignored correctly |
| Every model in manifest resolves to a real model | `resolve_model("claude-code", "max")` returns valid ID |
| `models.yaml` matches manifests | No drift between two sources of truth |
| `state_manifest.yaml` covers all YAML files | Guard test already exists (`test_yaml_manifest_complete.py`) |
| CLI surface matches documented commands | `--help` output matches README |

**Rule:** if you change a manifest, you must update the contract test. The ratchet guard is the model.

---

## Category 7 — REGRESSION (`tests/regression/`)

**Required: YES. Blocking on fail.**

Every bug fix must include a regression test that:

| Test | Covers |
|------|--------|
| Reproduces the exact bug | Fails before fix, passes after fix |
| Covers the edge case that triggered it | NULL metadata, 0 counters, duplicate PIDs |
| Tests the interaction, not just the function | Two functions that broke when combined |

**Rule:** no fix ships without a regression test. Today's 8 bugs → 8 regression tests → 15 written ✅

---

## Category 8 — E2E (`tests/e2e/`)

**Required: RECOMMENDED. Non-blocking but warns.**

Full user workflows through the CLI. Tests the system exactly as an operator would:

| Test | Covers |
|------|--------|
| `init → task create → delegate → verify → close` | Full task lifecycle |
| `discuss start → dispatch rounds → consensus → close` | Full discussion flow |
| `doctor` reports healthy project | All checks pass |
| `shux status --fix` cleans orphans | GC repairs broken state |

**Rule:** run on release candidates. Too slow for every PR.

---

## Category 9 — PERFORMANCE (`tests/perf/`)

**Required: OPTIONAL. Informational only.**

| Test | Covers |
|------|--------|
| 1,000 inbox items → dispatch latency | Watcher loop doesn't degrade |
| 10,000 archived tasks → status query time | SQLite indexing works |
| Large discussion (10 participants × 5 rounds) | Discussion engine scales |

---

## Enforcement — CI gates (current as of 2026-05-26)

| Gate | Required? | Blocking? | Current tests | Status |
|------|-----------|-----------|---------------|--------|
| Smoke | ✅ Yes | ✅ Blocking | 317 | ✅ Implemented |
| Unit | ✅ Yes | ✅ Blocking | 3,602 | ✅ Existing |
| Integration | ✅ Yes | ✅ Blocking | 255 | ✅ Implemented |
| State machine | ✅ Yes | ✅ Blocking | 325 | ✅ Implemented |
| Contract | ✅ Yes | ✅ Blocking | 128 | ✅ Implemented |
| Regression | ✅ Yes | ✅ Blocking | per bug | ✅ Added per fix |
| Chaos | ⚠️ Recommend | ❌ Warn | 14 | ✅ Implemented |
| E2E | ⚠️ Recommend | ❌ Warn | 155 | ✅ Implemented |
| Performance | ❌ Optional | ❌ Info | 2 | Minimal |

**Total: ~4,800 tests across 9 categories** (excluding existing 3,500+ unit tests that predate this strategy).

---

## Test file layout

```
tests/
├── smoke/
│   └── test_basic_commands.py           ← does it start?
├── unit/
│   ├── test_orchestrator.py             ← existing (24 tests)
│   ├── test_delegate_orchestrator.py    ← existing (5 tests)
│   ├── test_discuss_enqueue.py          ← existing (9 tests)
│   ├── test_discussion_dispatch.py      ← existing + retry tests
│   ├── test_gc_comprehensive.py         ← NEW (15 tests)
│   └── ...                               (3,500+ existing)
├── integration/                          ← 255 tests
│   ├── test_task_lifecycle.py           ← create → dispatch → close
│   ├── test_discussion_lifecycle.py     ← start → rounds → consensus
│   ├── test_orchestrator_pipeline.py    ← auto-orchestrate default
│   ├── test_gc_pipeline.py              ← all GC functions together
│   └── test_launcher_contract.py        ← effort + model propagation
├── state_machine/                        ← 325 tests
│   ├── test_transitions.py              ← all legal/illegal moves
│   ├── test_lifecycle_timeouts.py       ← timeout rules fire
│   └── test_discussion_round_lifecycle.py
├── contract/                             ← partially exists
│   ├── test_no_state_yaml_reads.py      ← existing (3 tests) ✅
│   ├── test_manifest_effort.py          ← NEW — supports_effort enforced
│   └── test_manifest_model_resolution.py ← NEW
├── chaos/
│   └── test_failure_injection.py        ← NEW
├── regression/
│   └── (each bug gets a file in its module)
└── e2e/
    └── test_full_workflow.py            ← existing (some)
```

---

## Priority — status (2026-05-25)

```
Week 1:  Integration (task lifecycle + discussion lifecycle)  ← ✅ DONE (110 tests)
Week 2:  State machine (all transitions)                      ← ✅ DONE (306 tests)
Week 3:  Contract (manifest ↔ launcher)                       ← ✅ DONE (122 tests)
Week 4:  Chaos (failure injection)                            ← ✅ DONE (14 tests, natural ceiling)
```

**Remaining:** E2E tests for release candidates. Performance benchmarks (optional).
