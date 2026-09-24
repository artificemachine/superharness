# CONCEPT — OpenProse, Reactor and CrossProse adaptation

Status: architectural reference only; no integration is approved or implemented.

Merged 2026-09-18 from `ADAPTATION-openprose-reactor.md`,
`CONCEPT-openprose-reactor-pilot.md` and `ARCH-openprose-superharness-sdd.md`.
Ownership of the upstream OpenProse/Reactor/CrossProse documentation stays with
the companion `crossprose` repository — see `REFERENCE-openprose-crossprose.md`.

---

## Part 1 — OpenProse and Reactor Adaptation Analysis

Status: architectural reference only; no integration is approved or implemented.

### Scope and ownership

CrossProse owns OpenProse education, migration research, and examples. This document owns only Superharness-specific decisions about patterns that may be adopted, adapted, or rejected.

Upstream baseline: [openprose/prose at `f9bb548`](https://github.com/openprose/prose/tree/f9bb548e8b9aba0eb48b472db9c325af2b1f2e86), OpenProse skill v0.15.0, runtime contract 2.

### Decisions

| OpenProse/Reactor pattern | Decision for Superharness | Reason |
|---|---|---|
| Explicit capability declarations | Adopt | Already reflected by task `requires` preflight; keep SQLite authoritative. |
| Postcondition-gated publication | Adapt | A task should close only after verification; preserve the existing review lifecycle. |
| Content-addressed receipts | Adapt | Hash task artifacts and evidence, but retain actor and timestamp in the Superharness audit trail. |
| Fingerprint-based selective wake | Investigate | Could suppress unchanged scheduled work, but must not replace dependency or lifecycle checks. |
| Deterministic wake decision | Adopt as principle | Routing may be intelligent; the decision to enqueue should remain explainable and reproducible. |
| Reactor DAG scheduler | Reject | Duplicates Superharness task dependencies, watcher, dispatch, and recovery. |
| Reactor world-model store | Reject | Creates a second runtime source of truth beside SQLite. |
| Reactor receipt ledger as audit SoT | Reject | Upstream receipts currently omit actor and timestamp identity. |
| `/prose-run` runtime dependency | Reject | Skills are an authoring surface, not a stable Superharness runtime boundary. |

### Optional future boundary

If a real Reactor use case is approved later, integrate it as an external workload:

```text
Superharness task and approval lifecycle
                ↓ supervise
optional Reactor CLI/SDK workload
                ↓ report
hashed artifacts and summarized receipts
```

SQLite would store only the Superharness task state, external run status, evidence pointers, and approvals. Reactor would retain its own compiled graph and world-model state. Neither system would mirror the other's internal nodes.

### Guardrails

- No dependency on a CrossProse development checkout.
- No automatic commit, push, merge, release, or deploy from Reactor.
- No duplicated task lifecycle or scheduler.
- No copied upstream syntax reference; link to the canonical CrossProse documentation.
- Any implementation requires a separate ADR, TDD plan, and owner approval.

---

## Part 2 — OpenProse/Reactor Pilot for Superharness

Status: decision input for the next planning session; no implementation is approved.

### Decision

The combination is promising as natural-language, agentic SDD, but only as an optional proof of concept. Reactor must not become a required Superharness dependency until reproduced evidence shows lower cost or better traceability.

### System roles

| Component | Authority |
|---|---|
| OpenProse `.prose.md` | Desired state and postconditions |
| Reactor | Contract compilation, drift detection, selective wake, world-model, receipts |
| Superharness | Finite tasks, agent routing, worktrees, TDD, approvals, actor/time audit |

### SDD contract

```text
spec hash → Reactor drift → Shux task → diff/tests → Shux verification → Reactor postconditions
```

- Every implementation task must reference a responsibility, facet, and spec hash.
- Acceptance criteria derive from the specification; requirement changes edit the spec first.
- Completion requires both Superharness verification and Reactor postconditions.
- Traceability must connect spec, task, diff, tests, artifacts, and receipts.

### Pilot scope

- One read-only standing responsibility: maintain a release-readiness report.
- Run Reactor as an optional external CLI workload supervised by one Shux task.
- Pin the OpenProse/Reactor version; do not depend on `/prose-run` or a development checkout.
- Reactor owns its graph/world-model state; SQLite owns task lifecycle, approvals, and evidence pointers.
- No custom `RenderBackend`, node-to-task mirroring, commit, push, merge, release, or deploy.

### Evidence gates

1. Initial run publishes a valid report and receipts.
2. Two repeated no-change runs independently show the expected memo-skip behavior.
3. One controlled input change wakes only the expected responsibility.
4. A postcondition failure preserves the prior valid truth and is visible to Superharness.
5. Superharness records hashed artifacts plus actor/time without copying Reactor's internal state.
6. No execution path bypasses `pending_user_approval` for outward actions.

### Next planning session

Start with `ADAPTATION-openprose-reactor.md` and `ARCH-openprose-superharness-sdd.md`. Write a TDD plan with RED tests for the evidence gates before adding any adapter code. Stop if the pilot requires a second scheduler or duplicate source of truth.

---

## Part 3 — OpenProse and Superharness as an SDD System

OpenProse and Superharness form a spec-driven development system only when the OpenProse contract drives and gates Superharness work. Installing Reactor beside Superharness is not sufficient.

```text
.prose.md specification
        ↓ compile
Reactor detects unmet responsibility/postcondition
        ↓
Superharness receives a finite implementation task
        ↓
TDD: RED → GREEN → REFACTOR
        ↓
Superharness verifies tests and evidence
        ↓
Reactor verifies the maintained truth
        ↓
Spec → task → diff → tests → receipts
```

The integration requires:

- `.prose.md` is the authoritative desired state.
- Every Shux task links to a responsibility, facet, and spec hash.
- Acceptance criteria derive from the specification.
- Implementation cannot silently change the specification.
- Completion requires Superharness verification and Reactor postconditions.
- Requirement changes modify the specification first.
- Traceability connects specification, task, code diff, tests, and receipts.

This is natural-language or agentic SDD. It is weaker than classical formal SDD because OpenProse compilation involves an intelligent agent, but stronger than ordinary prompt-driven development because the specification is persistent, versioned, executable, and verified.

OpenProse defines what must remain true, Reactor detects drift, and Superharness delivers and verifies finite code changes.
