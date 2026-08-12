# OpenProse and Reactor Adaptation Analysis

Status: architectural reference only; no integration is approved or implemented.

## Scope and ownership

CrossProse owns OpenProse education, migration research, and examples. This document owns only Superharness-specific decisions about patterns that may be adopted, adapted, or rejected.

Upstream baseline: [openprose/prose at `f9bb548`](https://github.com/openprose/prose/tree/f9bb548e8b9aba0eb48b472db9c325af2b1f2e86), OpenProse skill v0.15.0, runtime contract 2.

## Decisions

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

## Optional future boundary

If a real Reactor use case is approved later, integrate it as an external workload:

```text
Superharness task and approval lifecycle
                ↓ supervise
optional Reactor CLI/SDK workload
                ↓ report
hashed artifacts and summarized receipts
```

SQLite would store only the Superharness task state, external run status, evidence pointers, and approvals. Reactor would retain its own compiled graph and world-model state. Neither system would mirror the other's internal nodes.

## Guardrails

- No dependency on a CrossProse development checkout.
- No automatic commit, push, merge, release, or deploy from Reactor.
- No duplicated task lifecycle or scheduler.
- No copied upstream syntax reference; link to the canonical CrossProse documentation.
- Any implementation requires a separate ADR, TDD plan, and owner approval.
