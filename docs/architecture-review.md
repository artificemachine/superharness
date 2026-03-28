# Superharness — Architecture Review

**Date:** 2026-03-27
**Reviewer:** Claude (Software Architect)
**Version Reviewed:** 1.2.7
**Verdict:** Well-Architected, Production-Ready for Its Scope

---

## Strengths (What's Working Well)

### 1. Contract-First Design
Single source of truth in `contract.yaml` eliminates agent collision. The explicit handoff protocol (plan -> approve -> implement -> report -> verify -> close) enforces accountability at every step.

### 2. Layered Architecture
Clean three-tier separation:
```
CLI (Click) -> Commands (28 modules) -> Engine (pure logic, YAML I/O only)
```
Engine modules have no side effects beyond file operations — this makes them highly testable.

### 3. Append-Only Ledger
`ledger.md` is git-native, grep-friendly, and impossible to silently corrupt. Smart design choice for audit trail.

### 4. Module System
The YAML-template + lifecycle-hook pattern is elegant. Modules are independently testable, zero-config, and opt-in. The action registry decouples module definitions from implementations.

### 5. Security Model
Heartbeat ID allowlist prevents YAML injection. Explicit bypass flags (`--confirm-non-interactive`, `--confirm-skip-permissions`) force conscious opt-in to dangerous modes. Monitor UI binds to loopback only with per-session token.

### 6. Test Coverage
942 tests across unit/integration/E2E with subprocess testing (CLI parity), atomicity tests, cross-platform coverage, and regression guards.

---

## Concerns (Architectural Risks)

### Critical

#### C1. No YAML Schema Validation
`contract.yaml`, `handoff.yaml`, `inbox.yaml` — none are validated against a formal schema. A malformed YAML file (typo in status field, missing required key) will silently corrupt state and may only surface as a confusing runtime error downstream.

- **Risk:** Silent state corruption, especially in unattended watcher mode
- **Recommendation:** Add pydantic models (or jsonschema) for all protocol files. Validate on read, not just during `hygiene` checks. The `profile.schema.yaml` template exists but isn't enforced at runtime.

#### C2. File-Based Locking Without Deadlock Recovery
`inbox.py` uses `mkdir()` as an atomic lock (Unix) and `fcntl`/`msvcrt` — but there's no automatic deadlock detection or stale-lock cleanup with timeout.

- **Risk:** A crashed process leaves a lock file forever, blocking all dispatch
- **Recommendation:** Add PID + timestamp to lock file. On acquire failure, check if owning PID is alive. Auto-break locks older than N seconds (e.g., 300s).

### High

#### C3. CLI Dispatches Commands via Subprocess
`cli.py` routes commands by spawning `python3 -m superharness.commands.<name>` as subprocesses. This means:
- ~200ms overhead per command (Python startup)
- No shared state between command invocations
- Error propagation relies on exit codes only

This is fine for a CLI tool, but if superharness ever needs to become a library (imported by other Python code), this architecture will need restructuring.

- **Recommendation:** Consider refactoring high-frequency commands (contract queries, inbox checks) to also expose a Python API alongside the subprocess interface. Engine modules already support this — the gap is in the command layer.

#### C4. Single-File Contract Scalability
All tasks live in one `contract.yaml`. For a solo dev with <50 tasks, this is fine. But the protocol aspires to team use (`team_size: team`), where hundreds of tasks could make the file unwieldy.

- **Recommendation:** Document the scaling ceiling explicitly (e.g., "designed for <200 tasks per contract"). For future team scale, consider contract sharding by ID prefix or task archival (move `done` tasks to `contract-archive.yaml`).

#### C5. Hardcoded Model Strings
`model_router.py` and `sdk_runner.py` contain hardcoded model IDs (`gpt-5.2`, `gpt-5.3-codex`, `gpt-5.4` for Codex; Claude model IDs for Claude). These will break when providers update model names.

- **Recommendation:** Move model mappings to a config file or `profile.yaml` field. The `default_model` profile field exists but doesn't map to actual model IDs.

### Medium

#### C6. No Graceful Degradation on Partial Writes
YAML writes use temp file + atomic rename (good), but if the process dies between writing a handoff and updating contract status, state becomes inconsistent. The `hygiene` command catches this after the fact, but doesn't auto-repair.

- **Recommendation:** Add a `--repair` flag to `hygiene` that can reconcile orphaned handoffs with contract state. Currently hygiene is read-only.

#### C7. Watcher Interval is Fixed
The watcher polls at a fixed interval (default 15s). For idle projects this wastes resources; for active projects it may be too slow.

- **Recommendation:** Adaptive polling — back off when inbox is empty (exponential to max 5min), snap back to fast poll when items are enqueued. Simple to implement, meaningful resource savings.

#### C8. Discussion Protocol Complexity
The multi-round consensus system (`discuss.py`, `discussion.py`, `discussion_dispatch.py`) adds significant complexity for a feature that primarily targets multi-agent disagreement resolution. For a solo-dev tool, this is over-engineered.

- **Recommendation:** Mark this as an advanced/experimental feature. Consider gating it behind a module rather than having it in core commands.

### Low

#### C9. Monitor UI Security
The browser dashboard uses a per-session token printed to terminal, but there's no CSRF protection or rate limiting on mutating endpoints. Since it's loopback-only, the risk is low but non-zero (local browser-based attacks).

#### C10. No Telemetry or Usage Analytics
There's no way to understand how the tool is being used, which commands are popular, or where users get stuck. For an open-source project seeking adoption, this is a missed opportunity.

---

## Design Patterns Assessment

| Pattern | Implementation | Grade |
|---------|---------------|-------|
| Separation of Concerns | CLI -> Commands -> Engine -> State | **A** |
| Immutability | Ledger append-only, handoffs immutable | **A** |
| Extensibility | Module system with lifecycle hooks | **A** |
| Error Handling | Exit codes + printed diagnostics | **B+** |
| Atomicity | Temp file + rename for writes | **B+** |
| Concurrency | File-based locking (no deadlock recovery) | **B-** |
| Schema Validation | Hygiene checks only (no runtime validation) | **C+** |
| Configuration Management | Hardcoded values in engine modules | **C+** |

---

## Dependency Health

| Dependency | Version | Risk | Notes |
|------------|---------|------|-------|
| `click>=8.1` | Stable | Low | Mature, well-maintained |
| `pyyaml>=6.0` | Stable | Low | Industry standard |
| `ruamel.yaml>=0.18` | Stable | Low | Good for round-trip YAML |
| `pytest>=9.0,<10` | Dev only | Low | Pin is appropriate |
| `claude_agent_sdk` | Optional | Medium | API may change, graceful fallback exists |

Dependency surface is minimal — a strength for a CLI tool.

---

## Top 5 Recommendations (Priority Order)

1. **Add runtime schema validation** for protocol YAML files (pydantic or jsonschema). This is the single highest-impact improvement for reliability, especially in unattended mode.

2. **Add stale-lock detection** to file-based locking — PID check + age-based auto-break. Without this, a single crash can permanently block dispatch.

3. **Externalize model mappings** to config. Hardcoded model strings are a maintenance burden and a breaking change waiting to happen.

4. **Add `hygiene --repair`** for auto-reconciliation of inconsistent state (orphaned handoffs, stuck statuses).

5. **Document scaling limits** explicitly. The tool works well for its intended scope (solo/small team, <200 tasks). Make that boundary visible so users don't hit it unexpectedly.

---

## Summary

Superharness is a thoughtfully designed coordination framework that solves a real problem (multi-agent session continuity) with minimal dependencies and strong engineering practices. The file-based, protocol-driven approach is the right call for this use case — it's portable, auditable, and git-native.

The main architectural debt is in **defensive validation** (schema enforcement, lock recovery, state repair) — the happy path is solid, but edge cases in failure scenarios need hardening, especially for the unattended watcher mode where no human is watching.

Overall: **ship-ready for solo/small-team use**, with clear paths to harden for broader adoption.
