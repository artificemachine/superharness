# OpenProse/Reactor Pilot for Superharness

Status: decision input for the next planning session; no implementation is approved.

## Decision

The combination is promising as natural-language, agentic SDD, but only as an optional proof of concept. Reactor must not become a required Superharness dependency until reproduced evidence shows lower cost or better traceability.

## System roles

| Component | Authority |
|---|---|
| OpenProse `.prose.md` | Desired state and postconditions |
| Reactor | Contract compilation, drift detection, selective wake, world-model, receipts |
| Superharness | Finite tasks, agent routing, worktrees, TDD, approvals, actor/time audit |

## SDD contract

```text
spec hash → Reactor drift → Shux task → diff/tests → Shux verification → Reactor postconditions
```

- Every implementation task must reference a responsibility, facet, and spec hash.
- Acceptance criteria derive from the specification; requirement changes edit the spec first.
- Completion requires both Superharness verification and Reactor postconditions.
- Traceability must connect spec, task, diff, tests, artifacts, and receipts.

## Pilot scope

- One read-only standing responsibility: maintain a release-readiness report.
- Run Reactor as an optional external CLI workload supervised by one Shux task.
- Pin the OpenProse/Reactor version; do not depend on `/prose-run` or a development checkout.
- Reactor owns its graph/world-model state; SQLite owns task lifecycle, approvals, and evidence pointers.
- No custom `RenderBackend`, node-to-task mirroring, commit, push, merge, release, or deploy.

## Evidence gates

1. Initial run publishes a valid report and receipts.
2. Two repeated no-change runs independently show the expected memo-skip behavior.
3. One controlled input change wakes only the expected responsibility.
4. A postcondition failure preserves the prior valid truth and is visible to Superharness.
5. Superharness records hashed artifacts plus actor/time without copying Reactor's internal state.
6. No execution path bypasses `pending_user_approval` for outward actions.

## Next planning session

Start with `ADAPTATION-openprose-reactor.md` and `ARCH-openprose-superharness-sdd.md`. Write a TDD plan with RED tests for the evidence gates before adding any adapter code. Stop if the pilot requires a second scheduler or duplicate source of truth.
